// SPDX-License-Identifier: MIT
// NativeAOT C facade over the complete vendored Ryujinx C# shader translator.
// No game-specific hashes, precompiled shader lists, or private game data.
using Ryujinx.Graphics.Shader;
using Ryujinx.Graphics.Shader.Translation;
using System;
using System.IO;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

[StructLayout(LayoutKind.Sequential)]
public unsafe struct SnxRyuResult
{
    public byte* Spirv;
    public nuint SpirvBytes;
    public byte* ReflectionJson;
    public nuint ReflectionBytes;
    public byte* Error;
    public nuint ErrorBytes;
}

static unsafe partial class SwshXlate
{
    [UnmanagedCallersOnly(EntryPoint = "snx_ryu_api_version", CallConvs = new[] { typeof(CallConvCdecl) })]
    public static int ApiVersion() => 1;

    static byte* Owned(ReadOnlySpan<byte> value)
    {
        byte* dst = (byte*)NativeMemory.Alloc((nuint)value.Length + 1);
        if (dst == null) throw new OutOfMemoryException();
        value.CopyTo(new Span<byte>(dst, value.Length));
        dst[value.Length] = 0;
        return dst;
    }

    static void Release(SnxRyuResult* r)
    {
        if (r == null) return;
        NativeMemory.Free(r->Spirv);
        NativeMemory.Free(r->ReflectionJson);
        NativeMemory.Free(r->Error);
        *r = default;
    }

    [UnmanagedCallersOnly(EntryPoint = "snx_ryu_free_v1", CallConvs = new[] { typeof(CallConvCdecl) })]
    public static void Free(SnxRyuResult* r) => Release(r);

    static byte[] Reflect(ShaderProgram p, Accessor accessor, string stage)
    {
        using var mem = new MemoryStream();
        using (var w = new Utf8JsonWriter(mem))
        {
            w.WriteStartObject();
            w.WriteNumber("abi", 1);
            w.WriteString("stage", stage);
            w.WriteBoolean("uses_frag_coord", p.Info.UsesFragCoord);
            w.WriteNumber("frag_out_map", p.Info.FragmentOutputMap);
            w.WriteStartArray("cbufs");
            foreach (var x in p.Info.CBuffers)
            {
                w.WriteStartObject(); w.WriteNumber("binding", x.Binding);
                w.WriteNumber("slot", x.Slot); w.WriteEndObject();
            }
            w.WriteEndArray();
            w.WriteStartArray("sbufs");
            foreach (var x in p.Info.SBuffers)
            {
                w.WriteStartObject(); w.WriteNumber("binding", x.Binding);
                w.WriteNumber("slot", x.Slot); w.WriteNumber("cb_slot", x.SbCbSlot);
                w.WriteNumber("cb_offset", x.SbCbOffset);
                w.WriteNumber("flags", (int)x.Flags); w.WriteEndObject();
            }
            w.WriteEndArray();
            w.WriteStartArray("textures");
            foreach (var x in p.Info.Textures)
            {
                w.WriteStartObject(); w.WriteNumber("binding", x.Binding);
                w.WriteNumber("type", (int)x.Type); w.WriteString("format", x.Format.ToString());
                w.WriteNumber("cbuf_slot", x.CbufSlot);
                w.WriteNumber("handle", x.HandleIndex);
                w.WriteNumber("array", x.ArrayLength);
                w.WriteBoolean("separate", x.Separate);
                w.WriteNumber("flags", (int)x.Flags); w.WriteEndObject();
            }
            w.WriteEndArray();
            w.WriteStartArray("images");
            foreach (var x in p.Info.Images)
            {
                w.WriteStartObject(); w.WriteNumber("binding", x.Binding);
                w.WriteNumber("type", (int)x.Type); w.WriteString("format", x.Format.ToString());
                w.WriteNumber("cbuf_slot", x.CbufSlot);
                w.WriteNumber("handle", x.HandleIndex);
                w.WriteNumber("array", x.ArrayLength);
                w.WriteBoolean("separate", x.Separate);
                w.WriteNumber("flags", (int)x.Flags); w.WriteEndObject();
            }
            w.WriteEndArray();
            w.WriteStartArray("notes");
            foreach (var n in accessor.Notes) w.WriteStringValue(n);
            w.WriteEndArray();
            w.WriteEndObject();
            w.Flush();
        }
        return mem.ToArray();
    }

    // 0=OK, -1=bad arguments, -2=translator/validation failed.
    // The C caller frees all result buffers with snx_ryu_free_v1.
    [UnmanagedCallersOnly(EntryPoint = "snx_ryu_translate_v1", CallConvs = new[] { typeof(CallConvCdecl) })]
    public static int TranslateNative(byte* code, nuint codeSize, byte* jobUtf8,
                                       nuint jobSize, SnxRyuResult* result)
    {
        if (result == null) return -1;
        *result = default;
        if (code == null || jobUtf8 == null || codeSize < 8 || codeSize > 1048576 ||
            codeSize % 8 != 0 || jobSize == 0 || jobSize > 262144) return -1;
        try
        {
            byte[] program = new ReadOnlySpan<byte>(code, (int)codeSize).ToArray();
            JsonObject job = JsonNode.Parse(new ReadOnlySpan<byte>(jobUtf8, (int)jobSize)) as JsonObject
                             ?? throw new ArgumentException("job must be JSON object");
            string stage = job["stage"]?.GetValue<string>() ?? "";
            if (stage != "ps" && stage != "vs" && stage != "cs")
                throw new ArgumentException("supported shader stages: vs, ps, cs");
            if (stage != "cs" && program.Length < 88)
                throw new ArgumentException("graphics shader is missing its 80-byte SPH");

            var accessor = new Accessor(program, job);
            var flags = (job["debug"] is JsonNode d && !d.GetValue<bool>()
                         ? 0 : TranslationFlags.DebugMode) |
                        (stage == "cs" ? TranslationFlags.Compute : 0);
            var ctx = Translator.CreateContext(0, accessor,
                new TranslationOptions(TargetLanguage.Spirv, TargetApi.Vulkan, flags));
            ShaderProgram p = ctx.Translate();
            if (UsesFloat64(p.BinaryCode))
            {
                job["softfloat64"] = true;
                accessor = new Accessor(program, job);
                ctx = Translator.CreateContext(0, accessor,
                    new TranslationOptions(TargetLanguage.Spirv, TargetApi.Vulkan, flags));
                p = ctx.Translate();
                accessor.Notes.Add("FP64 lowered to FP32");
            }
            byte[] spv = p.BinaryCode;
            if (spv == null || spv.Length < 20 || spv.Length > 4 * 1024 * 1024 ||
                spv.Length % 4 != 0 || BitConverter.ToUInt32(spv, 0) != 0x07230203)
                throw new InvalidDataException("Ryujinx did not produce valid SPIR-V header");
            byte[] metadata = Reflect(p, accessor, stage);
            result->Spirv = Owned(spv);
            result->SpirvBytes = (nuint)spv.Length;
            result->ReflectionJson = Owned(metadata);
            result->ReflectionBytes = (nuint)metadata.Length;
            return 0;
        }
        catch (Exception ex)
        {
            Release(result);
            try
            {
                string message = ex.GetType().Name + ": " + ex.Message;
                byte[] data = Encoding.UTF8.GetBytes(message.Length > 2048 ? message[..2048] : message);
                result->Error = Owned(data);
                result->ErrorBytes = (nuint)data.Length;
            }
            catch (Exception) { }
            return -2;
        }
    }
}
