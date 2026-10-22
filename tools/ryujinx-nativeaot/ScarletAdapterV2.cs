// SPDX-License-Identifier: MIT
// ABI 2 keeps Ryujinx's support UBO intact. Its binding aliases ScarletNX's
// native fragment resolution UBO: only one of the two shaders runs per draw.
using Ryujinx.Graphics.Shader;
using Ryujinx.Graphics.Shader.Translation;
using System.Buffers.Binary;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json.Nodes;

[StructLayout(LayoutKind.Sequential)]
public unsafe struct SnxRyuScarletMetaV2
{
    public uint Version, Stage, CbufMask, InputMask, OutputMask, TextureCount;
    // cb0, word0, cb1, word1/constant, handle mode, type, array, shadow
    public fixed uint TextureInfo[64 * 8];
}

static class ScarletSpirvAdapterV2
{
    public const uint SupportBinding = 106; // SNX_VKB_RS, shader.h at pinned 34853ee

    private static string Literal(ReadOnlySpan<uint> a)
    {
        var b = new List<byte>();
        foreach (uint w in a)
            for (int s = 0; s < 32; s += 8)
            {
                byte c = (byte)(w >> s);
                if (c == 0) return Encoding.UTF8.GetString(b.ToArray());
                b.Add(c);
            }
        throw new InvalidDataException("unterminated SPIR-V literal");
    }

    public static unsafe byte[] Transform(ShaderProgram program, SnxRyuScarletMetaV2* meta,
                                          int defaultTextureBuffer)
    {
        *meta = default;
        meta->Version = 2;
        meta->Stage = 4;
        if (program.Info.Stage != ShaderStage.Fragment || program.Info.SBuffers.Count != 0 ||
            program.Info.Images.Count != 0)
            throw new InvalidDataException("ABI 2 supports sampled fragment images and UBOs");
        var descriptors = new Dictionary<uint, uint> { [0] = SupportBinding };
        var targets = new HashSet<uint> { SupportBinding };
        foreach (var cb in program.Info.CBuffers)
        {
            uint slot = cb.Slot;
            if (cb.Set != 0 || cb.Binding <= 0 || slot >= 18 || !targets.Add(slot) ||
                !descriptors.TryAdd((uint)cb.Binding, slot))
                throw new InvalidDataException("invalid constant buffer reflection");
            meta->CbufMask |= 1u << (int)slot;
        }
        int i = 0;
        foreach (var tex in program.Info.Textures)
        {
            var basic = tex.Type & SamplerType.Mask;
            if (i >= 64 || tex.Set != 0 || tex.Binding <= 0 || tex.Separate ||
                tex.ArrayLength != 1 || tex.Format != TextureFormat.Unknown ||
                (tex.Type & SamplerType.Multisample) != 0 ||
                (basic != SamplerType.Texture2D && basic != SamplerType.Texture3D && basic != SamplerType.TextureCube) ||
                (basic == SamplerType.Texture3D && (tex.Type & SamplerType.Array) != 0) ||
                !descriptors.TryAdd((uint)tex.Binding, (uint)(34 + i)))
                throw new InvalidDataException("unsupported texture view or reflection");
            (int cb0, int cb1) = TextureHandle.UnpackSlots(tex.CbufSlot, defaultTextureBuffer);
            (int off0, int off1, TextureHandleType mode) = TextureHandle.UnpackOffsets(tex.HandleIndex);
            if ((uint)cb0 >= 18 || (uint)cb1 >= 18 ||
                (uint)mode > 3u)
                throw new InvalidDataException("unsupported texture handle source");
            int at = 8 * i++;
            meta->TextureInfo[at] = (uint)cb0;
            meta->TextureInfo[at + 1] = (uint)off0;
            meta->TextureInfo[at + 2] = (uint)cb1;
            meta->TextureInfo[at + 3] = (uint)off1;
            meta->TextureInfo[at + 4] = (uint)mode;
            meta->TextureInfo[at + 5] = basic == SamplerType.Texture2D ? 1u : basic == SamplerType.Texture3D ? 2u : 3u;
            meta->TextureInfo[at + 6] = (tex.Type & SamplerType.Array) != 0 ? 1u : 0u;
            meta->TextureInfo[at + 7] = (tex.Type & SamplerType.Shadow) != 0 ? 1u : 0u;
        }
        meta->TextureCount = (uint)i;
        byte[] bytes = program.BinaryCode;
        if (bytes.Length < 20 || bytes.Length > 4194304 || (bytes.Length & 3) != 0)
            throw new InvalidDataException("invalid SPIR-V size");
        uint[] w = new uint[bytes.Length / 4];
        for (i = 0; i < w.Length; i++) w[i] = BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(4 * i, 4));
        if (w[0] != 0x07230203 || w[1] != 0x00010300 || w[3] == 0 || w[3] > 1000000)
            throw new InvalidDataException("expected bounded SPIR-V 1.3");
        var instructions = new List<(uint Op, uint[] Args)>();
        var bindings = new Dictionary<uint, uint>();
        var sets = new Dictionary<uint, uint>();
        var storage = new Dictionary<uint, uint>();
        var locations = new Dictionary<uint, uint>();
        uint support = 0;
        bool fp64 = false, interlock = false;
        for (i = 5; i < w.Length;)
        {
            int n = (int)(w[i] >> 16);
            uint op = w[i] & 65535;
            if (n == 0 || n > w.Length - i) throw new InvalidDataException("invalid SPIR-V instruction");
            uint[] a = w.AsSpan(i + 1, n - 1).ToArray();
            instructions.Add((op, a));
            if (op == 5 && a.Length >= 2 && Literal(a.AsSpan(1)) == "support_buffer")
            {
                if (support != 0) throw new InvalidDataException("duplicate support buffer");
                support = a[0];
            }
            if (op == 71 && a.Length == 3)
            {
                if (a[1] == 33) bindings.Add(a[0], a[2]);
                if (a[1] == 34) sets.Add(a[0], a[2]);
                if (a[1] == 30) locations.Add(a[0], a[2]);
            }
            if (op == 59 && a.Length >= 3) storage[a[1]] = a[2];
            if (op == 22 && a.Length == 2 && a[1] == 64) fp64 = true;
            if (op is >= 5364 and <= 5369) interlock = true;
            i += n;
        }
        if (fp64 || interlock) throw new InvalidDataException("FP64 or interlock actually required");
        if (support == 0 || !bindings.TryGetValue(support, out uint sb) || sb != 0 ||
            !storage.TryGetValue(support, out uint sc) || sc != 2 ||
            bindings.Count != descriptors.Count || sets.Count != bindings.Count)
            throw new InvalidDataException("support buffer or reflection resource count mismatch");
        var seen = new HashSet<uint>();
        foreach (var (id, binding) in bindings)
            if (!storage.ContainsKey(id) || !sets.TryGetValue(id, out uint set) || set != 0 ||
                !descriptors.ContainsKey(binding) || !seen.Add(binding))
                throw new InvalidDataException("reflection/SPIR-V descriptor mismatch");
        foreach (var (id, location) in locations)
        {
            if (!storage.TryGetValue(id, out uint cls)) continue;
            if (cls == 1)
            {
                if (location >= 32) throw new InvalidDataException("input location overflow");
                meta->InputMask |= 1u << (int)location;
            }
            if (cls == 3)
            {
                if (location >= 8) throw new InvalidDataException("output location overflow");
                meta->OutputMask |= 1u << (int)location;
            }
        }
        var patched = w.Take(5).ToList();
        foreach (var (op, a) in instructions)
        {
            if (op == 17 && a.Length == 1 && (a[0] == 10 || a[0] == 5378)) continue;
            if (op == 10 && Literal(a) == "SPV_EXT_fragment_shader_interlock") continue;
            if (op == 71 && a.Length == 3 && (a[1] == 33 || a[1] == 34))
                a[2] = a[1] == 34 ? 1u : descriptors[bindings[a[0]]];
            // Do not inspect literal operands as if they were SSA ids. Keep every
            // access chain, pointer copy and load (including unused ones) intact.
            patched.Add(((uint)(a.Length + 1) << 16) | op);
            patched.AddRange(a);
        }
        byte[] result = new byte[patched.Count * 4];
        for (i = 0; i < patched.Count; i++) BinaryPrimitives.WriteUInt32LittleEndian(result.AsSpan(i * 4, 4), patched[i]);
        return result;
    }
}

static unsafe partial class SwshXlate
{
    [UnmanagedCallersOnly(EntryPoint = "snx_ryu_translate_scarlet_v2", CallConvs = new[] { typeof(CallConvCdecl) })]
    public static int TranslateScarletV2(byte* code, nuint codeSize, byte* jobUtf8, nuint jobSize,
        SnxRyuResult* result, SnxRyuScarletMetaV2* state,
        delegate* unmanaged[Cdecl]<int, int, int, uint*, int> query)
    {
        if (result == null || state == null) return -1;
        *result = default; *state = default;
        if (code == null || jobUtf8 == null || query == null || codeSize < 88 || codeSize > 65536 ||
            codeSize % 8 != 0 || jobSize == 0 || jobSize > 262144) return -1;
        try
        {
            var job = JsonNode.Parse(new ReadOnlySpan<byte>(jobUtf8, (int)jobSize)) as JsonObject
                ?? throw new InvalidDataException("shader job must be an object");
            if (job["stage"]?.GetValue<string>() != "ps") throw new InvalidDataException("fragment stage required");
            uint Read(int kind, int handle, int slot)
            {
                uint value = 0;
                if (query(kind, handle, slot, &value) != 1)
                    throw new InvalidDataException($"runtime GPU query unavailable: {kind}/{handle:X}/{slot}");
                return value;
            }
            byte[] machineCode = new ReadOnlySpan<byte>(code, (int)codeSize).ToArray();
            job["alpha_func"] = (int)Read(3, 0, 0);
            job["alpha_reference"] = BitConverter.Int32BitsToSingle((int)Read(4, 0, 0));
            var accessor = new Accessor(machineCode, job);
            accessor.RuntimeConstant = offset => Read(0, offset, 1);
            accessor.RuntimeSampler = (handle, slot) => (SamplerType)Read(1, handle, slot);
            accessor.RuntimeNormalized = (handle, slot) => Read(2, handle, slot) != 0;
            var ctx = Translator.CreateContext(0, accessor,
                new TranslationOptions(TargetLanguage.Spirv, TargetApi.Vulkan, TranslationFlags.DebugMode));
            ShaderProgram p = ctx.Translate();
            byte[] patched = ScarletSpirvAdapterV2.Transform(p, state, job["texture_buffer_index"]?.GetValue<int>() ?? 2);
            result->Spirv = Owned(patched); result->SpirvBytes = (nuint)patched.Length;
            byte[] metadata = Reflect(p, accessor, "ps");
            result->ReflectionJson = Owned(metadata); result->ReflectionBytes = (nuint)metadata.Length;
            return 0;
        }
        catch (Exception ex)
        {
            Release(result); *state = default;
            byte[] error = Encoding.UTF8.GetBytes(ex.GetType().Name + ": " + ex.Message);
            result->Error = Owned(error); result->ErrorBytes = (nuint)error.Length;
            return -2;
        }
    }
}
