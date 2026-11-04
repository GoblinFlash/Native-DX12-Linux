# MiniEngine histogram build/test component

Third-party source: Microsoft DirectX-Graphics-Samples,
MiniEngine/Core/Shaders/GenerateHistogramCS.hlsl and PostEffectsRS.hlsli.
The retained snapshot is identified by exact file SHA-256 and byte sizes in
sources.lock.json. Only revision prefix 68a2b1e9 has been verified; a full Git
revision is not established.

Copyright (c) 2015 Microsoft. License: MIT; the full original text is upstream/LICENSE and must accompany copies/substantial portions. The shader's original Microsoft copyright/MIT disclaimer, Developed by Minigraph and Author: James Stanard lines remain intact. Retain per-file original notices, including PostEffectsRS.hlsli. This material is not relicensed as Andrew-only GPL.

Project adaptation is explicitly marked NDX12 in adapted/histogram.hlsl:
luma Texture2D becomes a UAV structured buffer with explicit width, the constant
buffer is padded to 32 bytes, and the root-signature include/attribute is removed.
adaptation.patch retains the historical hunk bodies with portable relative file
headers.

The FFX builders use this component for ordinary-profile CPU/compiler regression
checks. Its inclusion does not qualify GPU execution. A future upstream fetch
recipe would need a complete source revision or an approved hash-addressed
snapshot acquisition method.
