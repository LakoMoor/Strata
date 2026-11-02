// Standalone transfer probe: nvcc -O3 tools/v100_transfer_probe.cu -o transfer-probe
// Reports decimal GB/s. Uses synthetic data, 256 MiB pinned RAM, 512 MiB per GPU.
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

static void check(cudaError_t code) {
    if (code != cudaSuccess) {
        std::fprintf(stderr, "%s\n", cudaGetErrorString(code));
        std::exit(1);
    }
}

int main() {
    constexpr size_t bytes = 256ull << 20;
    constexpr int repeats = 16;
    void *host = nullptr;
    check(cudaHostAlloc(&host, bytes, cudaHostAllocPortable));
    std::memset(host, 0, bytes);
    int count = 0;
    check(cudaGetDeviceCount(&count));
    for (int device = 0; device < count; ++device) {
        check(cudaSetDevice(device));
        cudaDeviceProp props{};
        check(cudaGetDeviceProperties(&props, device));
        void *a = nullptr, *b = nullptr;
        check(cudaMalloc(&a, bytes));
        check(cudaMalloc(&b, bytes));
        cudaEvent_t start, end;
        check(cudaEventCreate(&start));
        check(cudaEventCreate(&end));
        check(cudaMemcpy(a, host, bytes, cudaMemcpyHostToDevice));
        check(cudaDeviceSynchronize());
        auto measure = [&](bool host_to_device) {
            check(cudaEventRecord(start));
            for (int i = 0; i < repeats; ++i)
                check(cudaMemcpyAsync(host_to_device ? a : b, host_to_device ? host : a,
                                      bytes, host_to_device ? cudaMemcpyHostToDevice : cudaMemcpyDeviceToDevice));
            check(cudaEventRecord(end));
            check(cudaEventSynchronize(end));
            float ms = 0;
            check(cudaEventElapsedTime(&ms, start, end));
            // D2D counts payload once, not the sum of reads and writes.
            return double(bytes) * repeats / (ms * 1e6);
        };
        double h2d = measure(true), d2d = measure(false);
        int peer = 0;
        if (count == 2) check(cudaDeviceCanAccessPeer(&peer, device, 1 - device));
        std::printf("{\"gpu\":%d,\"name\":\"%s\",\"sm\":%d,\"bytes\":%zu,"
                    "\"repeats\":%d,\"h2d_GBs\":%.3f,\"d2d_payload_GBs\":%.3f,\"peer_capable\":%s}\n",
                    device, props.name, props.major * 10 + props.minor, bytes, repeats,
                    h2d, d2d, peer ? "true" : "false");
        check(cudaEventDestroy(start));
        check(cudaEventDestroy(end));
        check(cudaFree(a));
        check(cudaFree(b));
    }
    check(cudaFreeHost(host));
}
