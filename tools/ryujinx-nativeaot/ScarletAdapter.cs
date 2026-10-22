// SPDX-License-Identifier: MIT
// An automatic, fail-closed Ryujinx -> ScarletNX SPIR-V adapter.
// Operates on ANY fragment Maxwell shader, without any per-game shader key.
// This export is independent of snx_ryu_translate_v1 (the known-good ABI).
using Ryujinx.Graphics.Shader;
using Ryujinx.Graphics.Shader.Translation;
using System;
using System.Buffers.Binary;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json.Nodes;

[StructLayout(LayoutKind.Sequential)]
public unsafe struct SnxRyuScarletMeta
{
    public uint Version;      // 1
    public uint Stage;        // ST_FS=4
    public uint CbufMask;     // uniform CB slots 0..17
    public uint InputMask;    // generic fragment inputs 0..31
    public uint OutputMask;   // fragment colour outputs 0..7
    public uint TextureCount; // max 64; each entry is CB0, offset0, CB1, offset1
    public fixed uint TextureInfo[64 * 4];
}

static class ScarletSpirvAdapter
{
    private const uint OpName = 5, OpExtension = 10, OpCapability = 17;
    private const uint OpTypeFloat = 22, OpConstant = 43, OpVariable = 59;
    private const uint OpLoad = 61, OpAccessChain = 65, OpInBoundsAccessChain = 66;
    private const uint OpCopyObject = 83, OpDecorate = 71, OpEntryPoint = 15;
    private const uint DecorationBinding = 33, DecorationSet = 34, DecorationLocation = 30;
    private const uint CbCount = 18, TextureBase = 34, MaxTextures = 64;

    private readonly record struct Inst(uint Opcode, uint[] A);
    private readonly record struct Descriptor(uint Id, uint Old, uint Set, uint Target);

    private static string WordString(ReadOnlySpan<uint> data)
    {
        var bytes = new List<byte>(data.Length * 4);
        foreach (uint word in data)
        {
            for (int shift = 0; shift < 32; shift += 8)
            {
                byte b = (byte)(word >> shift);
                if (b == 0) return Encoding.UTF8.GetString(bytes.ToArray());
                bytes.Add(b);
            }
        }
        throw new InvalidDataException("unterminated SPIR-V literal");
    }

    private static List<Inst> Parse(ReadOnlySpan<byte> bytes, out uint[] header)
    {
        if (bytes.Length < 20 || (bytes.Length & 3) != 0 || bytes.Length > 4 * 1024 * 1024)
            throw new InvalidDataException("invalid SPIR-V bytes");
        uint[] words = new uint[bytes.Length / 4];
        for (int i = 0; i < words.Length; i++)
            words[i] = BinaryPrimitives.ReadUInt32LittleEndian(bytes.Slice(4 * i, 4));
        if (words[0] != 0x07230203 || words[1] != 0x00010300 || words[3] > 1000000)
            throw new InvalidDataException("expected bounded SPIR-V 1.3");
        header = words.Take(5).ToArray();
        var instructions = new List<Inst>();
        for (int i = 5; i < words.Length;)
        {
            int count = (int)(words[i] >> 16);
            uint op = words[i] & 65535u;
            if (count < 1 || count > words.Length - i)
                throw new InvalidDataException("invalid SPIR-V instruction length");
            instructions.Add(new Inst(op, words.AsSpan(i + 1, count - 1).ToArray()));
            i += count;
        }
        return instructions;
    }

    private static void Add(List<uint> dst, uint op, params uint[] args)
    {
        dst.Add(((uint)(args.Length + 1) << 16) | op);
        dst.AddRange(args);
    }

    // Translation REFLECTION is the authority: the SPIR-V bindings are checked
    // exhaustively against it before any rewritten shader is handed to Vulkan.
    public static unsafe byte[] Transform(byte[] spirv, ShaderProgram program,
                                           SnxRyuScarletMeta* meta)
    {
        var desc = new Dictionary<uint, uint>();
        var seenTargets = new HashSet<uint>();
        *meta = default;
        meta->Version = 1;
        meta->Stage = 4;
        if (program.Info.SBuffers.Count != 0 || program.Info.Images.Count != 0)
            throw new InvalidDataException("SSBO/storage images require separate descriptor adapter");
        foreach (var cb in program.Info.CBuffers)
        {
            uint binding = unchecked((uint)cb.Binding);
            uint slot = unchecked((uint)cb.Slot);
            if (binding == 0 || binding > 1000 || slot >= CbCount || desc.ContainsKey(binding) ||
                !seenTargets.Add(slot))
                throw new InvalidDataException("unsupported or duplicated constant buffer binding");
            desc.Add(binding, slot);
            meta->CbufMask |= 1u << (int)slot;
        }
        int index = 0;
        foreach (var tex in program.Info.Textures)
        {
            uint binding = unchecked((uint)tex.Binding);
            uint handle = unchecked((uint)tex.HandleIndex);
            uint cbPair = unchecked((uint)tex.CbufSlot);
            uint cb0 = cbPair & 65535u;
            uint cb1 = (cbPair >> 16);
            int flags = (int)tex.Flags;
            if (index >= MaxTextures || binding == 0 || binding > 1000 || desc.ContainsKey(binding) ||
                (int)tex.Type != 3 || tex.Format.ToString() != "Unknown" ||
                (int)tex.ArrayLength != 1 || tex.Separate || (flags != 0 && flags != 2) ||
                ((handle >> 28) & 15) != 1 || cb1 == 0 || cb0 >= CbCount || cb1 - 1 >= CbCount)
                throw new InvalidDataException("texture type, descriptor, or combined TIC/TSC source unsupported");
            uint target = TextureBase + (uint)index;
            if (!seenTargets.Add(target))
                throw new InvalidDataException("duplicate target texture slot");
            desc.Add(binding, target);
            int at = index * 4;
            meta->TextureInfo[at] = cb0;
            meta->TextureInfo[at + 1] = handle & 0x3fffu;
            meta->TextureInfo[at + 2] = cb1 - 1;
            meta->TextureInfo[at + 3] = (handle >> 14) & 0x3fffu;
            index++;
        }
        meta->TextureCount = (uint)index;

        var instructions = Parse(spirv, out uint[] header);
        var names = new Dictionary<uint, string>();
        var bindings = new Dictionary<uint, uint>();
        var sets = new Dictionary<uint, uint>();
        var locations = new Dictionary<uint, uint>();
        var variables = new Dictionary<uint, uint>();
        var consts = new Dictionary<uint, (uint Type, uint Value)>();
        var fp32 = new HashSet<uint>();
        bool fp64 = false, interlockOpcode = false;

        foreach (var ins in instructions)
        {
            uint[] a = ins.A;
            if (ins.Opcode == OpName && a.Length >= 2)
                names[a[0]] = WordString(a.AsSpan(1));
            if (ins.Opcode == OpDecorate && a.Length >= 3)
            {
                if (a[1] == DecorationBinding) bindings[a[0]] = a[2];
                if (a[1] == DecorationSet) sets[a[0]] = a[2];
                if (a[1] == DecorationLocation) locations[a[0]] = a[2];
            }
            if (ins.Opcode == OpVariable && a.Length >= 3) variables[a[1]] = a[2];
            if (ins.Opcode == OpTypeFloat && a.Length == 2)
            {
                if (a[1] == 32) fp32.Add(a[0]);
                if (a[1] == 64) fp64 = true;
            }
            if (ins.Opcode == OpConstant && a.Length == 3)
                consts[a[1]] = (a[0], a[2]);
            if (ins.Opcode is >= 5364 and <= 5369) interlockOpcode = true;
        }
        uint[] supports = names.Where(x => x.Value == "support_buffer").Select(x => x.Key).ToArray();
        if (supports.Length != 1 || !variables.TryGetValue(supports[0], out uint supportClass) ||
            supportClass != 2 || !bindings.TryGetValue(supports[0], out uint supportBinding) ||
            supportBinding != 0 || !sets.TryGetValue(supports[0], out uint supportSet) || supportSet != 0)
            throw new InvalidDataException("expected exactly one unused Ryujinx support_buffer at set0/binding0");
        uint support = supports[0];

        var allResources = bindings.Keys.Union(sets.Keys).ToHashSet();
        if (allResources.Count != desc.Count + 1)
            throw new InvalidDataException("reflection/SPIR-V resource count mismatch");
        var usedOriginal = new HashSet<uint>();
        foreach (uint id in allResources)
        {
            if (!sets.TryGetValue(id, out uint set) || set != 0 ||
                !bindings.TryGetValue(id, out uint old))
                throw new InvalidDataException("incomplete or nonzero SPIR-V descriptor set");
            if (id != support && (!desc.ContainsKey(old) || !usedOriginal.Add(old)))
                throw new InvalidDataException("reflection/SPIR-V descriptor mismatch");
        }
        if (usedOriginal.Count != desc.Count)
            throw new InvalidDataException("reflection descriptors not all present");

        uint floatOneType = 0, floatOneId = 0;
        foreach (var pair in consts.OrderBy(k => k.Value.Type).ThenBy(k => k.Key))
            if (fp32.Contains(pair.Value.Type) && pair.Value.Value == 0x3f800000u)
            {
                floatOneType = pair.Value.Type;
                floatOneId = pair.Key;
                break;
            }
        // An unused support buffer needs no synthesized float constant.

        var chains = new Dictionary<uint, uint>();
        var loads = new HashSet<uint>();
        foreach (var ins in instructions)
        {
            var a = ins.A;
            if ((ins.Opcode == OpAccessChain || ins.Opcode == OpInBoundsAccessChain) &&
                a.Length >= 4 && a[2] == support)
            {
                if (!consts.TryGetValue(a[3], out var indexValue) || indexValue.Value != 5)
                    throw new InvalidDataException("Ryujinx support_buffer reads unexpected field");
                chains.Add(a[1], a[0]);
            }
            if (ins.Opcode == OpLoad && a.Length >= 3 && chains.ContainsKey(a[2]))
            {
                if (a.Length != 3 || a[0] != floatOneType)
                    throw new InvalidDataException("Ryujinx render scale load is not float32");
                loads.Add(a[2]);
            }
        }
        if (!chains.Keys.ToHashSet().SetEquals(loads))
            throw new InvalidDataException("unsupported render scale pointer usage");
        // Ryujinx does not always emit a literal 1.0.  A render-scale
        // read can still be safely replaced with 1.0 at native resolution;
        // synthesize the SPIR-V constant instead of rejecting the shader.
        bool addFloatOne = loads.Count != 0 && floatOneId == 0;
        if (addFloatOne)
        {
            if (fp32.Count == 0 || header[3] == uint.MaxValue)
                throw new InvalidDataException("render scale needs a valid float32 type and SPIR-V id");
            floatOneType = fp32.Min();
            floatOneId = header[3]++;
        }
        foreach (var ins in instructions)
        {
            uint[] a = ins.A;
            if (ins.Opcode == OpEntryPoint && a.Contains(support))
                throw new InvalidDataException("support buffer used as entrypoint interface");
            bool knownName = (ins.Opcode == OpName || ins.Opcode == OpDecorate) &&
                             a.Length > 0 && a[0] == support;
            bool knownVar = ins.Opcode == OpVariable && a.Length >= 2 && a[1] == support;
            bool knownChain = (ins.Opcode == OpAccessChain || ins.Opcode == OpInBoundsAccessChain) &&
                              a.Length >= 4 && a[2] == support;
            bool knownLoad = ins.Opcode == OpLoad && a.Length >= 3 && loads.Contains(a[2]);
            if (knownName || knownVar || knownChain || knownLoad ||
                ins.Opcode == OpConstant || ins.Opcode == OpDecorate || ins.Opcode == 12)
                continue;
            if (a.Contains(support) || a.Any(x => chains.ContainsKey(x)))
                throw new InvalidDataException("unsupported support_buffer SSA reference");
        }

        foreach (var pair in locations)
        {
            if (!variables.TryGetValue(pair.Key, out uint storage)) continue;
            if (storage == 1)
            {
                if (pair.Value >= 32) throw new InvalidDataException("input location overflow");
                meta->InputMask |= 1u << (int)pair.Value;
            }
            if (storage == 3)
            {
                if (pair.Value >= 8) throw new InvalidDataException("output location overflow");
                meta->OutputMask |= 1u << (int)pair.Value;
            }
        }
        if (meta->OutputMask == 0)
            throw new InvalidDataException("fragment shader has no colour output");

        var patched = new List<uint>(spirv.Length / 4 + 8);
        patched.AddRange(header);
        bool insertedFloatOne = false;
        foreach (var ins in instructions)
        {
            // Constants must precede the first function in SPIR-V logical layout.
            if (addFloatOne && !insertedFloatOne && ins.Opcode == 54) // OpFunction
            {
                Add(patched, OpConstant, floatOneType, floatOneId, 0x3f800000u);
                insertedFloatOne = true;
            }
            uint[] a = ins.A;
            uint op = ins.Opcode;
            if ((op == OpName || op == OpDecorate) && a.Length > 0 && a[0] == support)
                continue;
            if (op == OpVariable && a.Length >= 2 && a[1] == support)
                continue;
            if ((op == OpAccessChain || op == OpInBoundsAccessChain) &&
                a.Length >= 4 && a[2] == support)
                continue;
            if (op == OpLoad && a.Length >= 3 && loads.Contains(a[2]))
            {
                Add(patched, OpCopyObject, floatOneType, a[1], floatOneId);
                continue;
            }
            if (op == OpCapability && a.Length == 1 && a[0] == 10)
            {
                if (fp64) throw new InvalidDataException("FP64 capability actually required");
                continue;
            }
            if (op == OpCapability && a.Length == 1 && a[0] == 5378)
            {
                if (interlockOpcode) throw new InvalidDataException("fragment interlock opcode present");
                continue;
            }
            if (op == OpExtension && WordString(a) == "SPV_EXT_fragment_shader_interlock")
                continue;
            if (op == OpDecorate && a.Length >= 3 && (a[1] == DecorationSet || a[1] == DecorationBinding) &&
                bindings.TryGetValue(a[0], out uint old))
            {
                if (a[0] == support) throw new InvalidDataException("support buffer decoration remains");
                if (!desc.TryGetValue(old, out uint target))
                    throw new InvalidDataException("unknown descriptor");
                Add(patched, op, a[0], a[1], a[1] == DecorationSet ? 1u : target);
                continue;
            }
            Add(patched, op, a);
        }
        if (addFloatOne && !insertedFloatOne)
            throw new InvalidDataException("SPIR-V missing function for render-scale replacement");
        if (patched.Count < 5 || patched.Count > 1024 * 1024)
            throw new InvalidDataException("rewritten SPIR-V size invalid");
        byte[] result = new byte[patched.Count * 4];
        for (int i = 0; i < patched.Count; i++)
            BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(i * 4, 4), patched[i]);
        return result;
    }
}

static unsafe partial class SwshXlate
{
    // 0: adapted shader + full dynamic descriptor metadata.
    // -1 invalid input; -2 unsupported reflection, shader or translator error.
    // All output allocations still freed through snx_ryu_free_v1.
    [UnmanagedCallersOnly(EntryPoint = "snx_ryu_translate_scarlet_v1",
                         CallConvs = new[] { typeof(CallConvCdecl) })]
    public static int TranslateScarlet(byte* code, nuint codeSize, byte* jobUtf8,
                                       nuint jobSize, SnxRyuResult* result,
                                       SnxRyuScarletMeta* state)
    {
        if (result == null || state == null) return -1;
        *result = default;
        *state = default;
        if (code == null || jobUtf8 == null || codeSize < 88 || codeSize > 65536 ||
            codeSize % 8 != 0 || jobSize == 0 || jobSize > 262144) return -1;
        try
        {
            byte[] machineCode = new ReadOnlySpan<byte>(code, (int)codeSize).ToArray();
            JsonObject job = JsonNode.Parse(new ReadOnlySpan<byte>(jobUtf8, (int)jobSize)) as JsonObject
                ?? throw new InvalidDataException("shader job must be JSON object");
            if (job["stage"]?.GetValue<string>() != "ps" ||
                job["debug"]?.GetValue<bool>() != true)
                throw new InvalidDataException("Scarlet bridge requires fragment DebugMode");
            var accessor = new Accessor(machineCode, job);
            TranslationFlags flags = TranslationFlags.DebugMode;
            var ctx = Translator.CreateContext(0, accessor,
                new TranslationOptions(TargetLanguage.Spirv, TargetApi.Vulkan, flags));
            ShaderProgram p = ctx.Translate();
            if (UsesFloat64(p.BinaryCode))
            {
                job["softfloat64"] = true;
                accessor = new Accessor(machineCode, job);
                ctx = Translator.CreateContext(0, accessor,
                    new TranslationOptions(TargetLanguage.Spirv, TargetApi.Vulkan, flags));
                p = ctx.Translate();
                accessor.Notes.Add("FP64 lowered to FP32");
            }
            byte[] patched = ScarletSpirvAdapter.Transform(p.BinaryCode, p, state);
            byte[] metadata = Reflect(p, accessor, "ps");
            result->Spirv = Owned(patched);
            result->SpirvBytes = (nuint)patched.Length;
            result->ReflectionJson = Owned(metadata);
            result->ReflectionBytes = (nuint)metadata.Length;
            return 0;
        }
        catch (Exception ex)
        {
            Release(result);
            *state = default;
            try
            {
                string message = ex.GetType().Name + ": " + ex.Message;
                byte[] data = Encoding.UTF8.GetBytes(message.Length > 2048 ? message[..2048] : message);
                result->Error = Owned(data);
                result->ErrorBytes = (nuint)data.Length;
            }
            catch (Exception) {}
            return -2;
        }
    }
}
