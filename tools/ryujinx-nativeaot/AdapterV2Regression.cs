// SPDX-License-Identifier: MIT
// Standalone CI harness compiled with the actual adapter and pinned Ryujinx.
using Ryujinx.Graphics.Shader;
using Ryujinx.Graphics.Shader.Translation;
using System.Buffers.Binary;

static unsafe class AdapterV2Regression
{
    static ShaderProgram Program(byte[] code, int mode, SamplerType type = SamplerType.Texture2D)
    {
        int handle = TextureHandle.PackOffsets(94, 352, (TextureHandleType)mode);
        var info = new ShaderProgramInfo([], [],
            [new TextureDescriptor(0, 1, type, TextureFormat.Unknown, TextureHandle.PackSlots(2, 2), handle,
                1, false, TextureUsageFlags.None)], [], ShaderStage.Fragment, 0, 0, 0, true, false, false, false, 0, 15);
        return new ShaderProgram(info, TargetLanguage.Spirv, code);
    }
    public static int Main(string[] args)
    {
        if (SupportBuffer.RequiredSize != 1392 || SupportBuffer.GraphicsRenderScaleOffset != 192)
            throw new Exception("pinned support-buffer ABI changed");
        byte[] original = File.ReadAllBytes(args[0]);
        int passed = 0;
        for (int mode = 0; mode <= 3; mode++)
        {
            SnxRyuScarletMetaV2 meta;
            byte[] result = ScarletSpirvAdapterV2.Transform(Program(original, mode), &meta, 2);
            if (meta.Version != 2 || meta.TextureCount != 1 || meta.TextureInfo[0] != 2 ||
                meta.TextureInfo[1] != 94 || meta.TextureInfo[2] != 2 || meta.TextureInfo[3] != 352 ||
                meta.TextureInfo[4] != mode || meta.OutputMask != 1)
                throw new Exception("descriptor metadata mismatch");
            // Only descriptor decorations may change in this no-FP64 fixture.
            if (result.Length != original.Length) throw new Exception("shader instructions were removed");
            for (int i = 20; i < original.Length;)
            {
                uint word = BinaryPrimitives.ReadUInt32LittleEndian(original.AsSpan(i, 4));
                int n = (int)(word >> 16) * 4;
                if ((word & 65535) != 71 && !original.AsSpan(i, n).SequenceEqual(result.AsSpan(i, n)))
                    throw new Exception("non-decoration instruction changed");
                i += n;
            }
            File.WriteAllBytes(args[1] + $"/adapter-mode-{mode}.spv", result);
            passed++;
        }
        foreach (var type in new[] {SamplerType.TextureBuffer, SamplerType.Texture2D | SamplerType.Multisample})
        {
            try { SnxRyuScarletMetaV2 m; ScarletSpirvAdapterV2.Transform(Program(original, 1, type), &m, 2); }
            catch (InvalidDataException) { passed++; continue; }
            throw new Exception("unsupported view silently accepted");
        }
        byte[] bad = (byte[])original.Clone(); bad[0] = 0;
        try { SnxRyuScarletMetaV2 m; ScarletSpirvAdapterV2.Transform(Program(bad, 1), &m, 2); }
        catch (InvalidDataException) { passed++; }
        if (passed != 7) throw new Exception("malformed module silently accepted");
        Console.WriteLine($"ADAPTER_V2_MANAGED_REGRESSIONS: {passed} passed");
        return 0;
    }
}
