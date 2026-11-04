RWStructuredBuffer<uint> output_buffer : register(u0, space0);

[numthreads(64, 1, 1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x < 65u)
        output_buffer[tid.x] = tid.x * 3u + 7u;
}
