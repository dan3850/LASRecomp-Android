// Compile the production movie adapter and IStorage together. Only unrelated
// guest services are discarded by --gc-sections; FFmpeg demux/decoding is real.
#include "fs_storage_harness.c"
#include "../runtime/hle/movie.c"
#include "../runtime/romfs_build.h"
#include <assert.h>
Settings g_settings = {.movie_audio = true};

int main(int argc, char **argv) {
    assert(argc == 2);
    char local[4096], file[4096], marker[4096], image[4096], manifest[512], why[512];
    snprintf(local, sizeof local, "%s/private", argv[1]); assert(!mkdir(local, 0700));
    snprintf(file, sizeof file, "%s/romfs/region_common/movie/test.webm", argv[1]);
    struct stat st; assert(!stat(file, &st));
    snprintf(manifest, sizeof manifest, "D\tregion_common\nD\tregion_common/movie\nF\t%llu\tregion_common/movie/test.webm\n",
             (unsigned long long)st.st_size);
    snprintf(marker, sizeof marker, "%s/.external-romfs-directory", local);
    FILE *f = fopen(marker, "wb"); assert(f); fputc(1, f); fclose(f);
    for (int mode = 0; mode < 2; mode++) {
        if (mode) {
            assert(!unlink(marker));
            char source[4096]; snprintf(source, sizeof source, "%s/romfs", argv[1]);
            snprintf(image, sizeof image, "%s/romfs.bin", argv[1]);
            assert(romfs_build(source, image, NULL, why, sizeof why));
        }
        assert(!test_mount(local, argv[1], manifest, NULL, 0));
        Extractor e = {0};
        uint64_t object[2] = {0, (uint64_t)(uintptr_t)&e};
        Cpu cpu = {0}; cpu.x[0] = (uint64_t)(uintptr_t)object;
        cpu.x[2] = (uint64_t)(uintptr_t)"rom:/region_common/movie/test.webm";
        ex_set_data_source(&cpu);
        assert(cpu.x[0] == 0 && e.fmt && e.io && e.ntracks == 1);
        AVStream *stream = e.fmt->streams[0];
        const AVCodec *codec = avcodec_find_decoder(stream->codecpar->codec_id);
        assert(codec);
        AVCodecContext *decoder = avcodec_alloc_context3(codec); assert(decoder);
        assert(avcodec_parameters_to_context(decoder, stream->codecpar) >= 0);
        assert(avcodec_open2(decoder, codec, NULL) >= 0);
        AVFrame *frame = av_frame_alloc(); assert(frame);
        int frames = 0;
        while (av_read_frame(e.fmt, e.pkt) >= 0) {
            assert(avcodec_send_packet(decoder, e.pkt) >= 0);
            while (avcodec_receive_frame(decoder, frame) >= 0) {
                assert(frame->width == 16 && frame->height == 16); frames++;
            }
            av_packet_unref(e.pkt);
        }
        assert(frames > 0);
        assert(av_seek_frame(e.fmt, -1, 0, AVSEEK_FLAG_BACKWARD) >= 0);
        assert(av_read_frame(e.fmt, e.pkt) >= 0);
        assert(romfs_movie_seek(&e, 0, AVSEEK_SIZE) == st.st_size);
        assert(romfs_movie_seek(&e, 0, SEEK_SET) == 0);
        uint8_t signature[4];
        assert(romfs_movie_read(&e, signature, 4) == 4);
        assert(!memcmp(signature, "\x1a\x45\xdf\xa3", 4));
        assert(romfs_movie_seek(&e, 0, SEEK_END) == st.st_size);
        assert(romfs_movie_read(&e, signature, 4) == AVERROR_EOF);
        assert(romfs_movie_seek(&e, INT64_MIN, SEEK_CUR) < 0);
        assert(romfs_movie_seek(&e, INT64_MAX, SEEK_CUR) < 0);
        av_frame_free(&frame); avcodec_free_context(&decoder);
        ex_close_source(&e); ex_close_source(&e);
        test_unmount();
        printf("FFmpeg: %s backend, demux/decode/seek/EOF PASS (%d frames)\n", mode ? "legacy image" : "external folder", frames);
    }
}
