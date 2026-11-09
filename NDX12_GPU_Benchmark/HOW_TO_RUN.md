# How to run

The instructions below apply to the benchmark release archive. Use the README and exact archive names shipped with your package. Running `git clone` downloads the source repository; it does not install the ready-to-run benchmark package.

1. **Get the release files and published checksums.** Download the benchmark archive and the separate starter, `ndx12_start.py`. Copy the three SHA-256 values from the release page: the archive, the starter and the archive's `MANIFEST.sha256`. Do not use a checksum file downloaded alongside the archive as your only reference, or calculate the trusted values from the downloaded files themselves.

2. **Prepare the machine.** Save your work and close games and other GPU-heavy programs; a driver fault may freeze the display. Do not change your driver just for this test. `/usr/bin/python3` must be standard CPython 3.13 or newer with the GIL enabled.

3. **Install the package and starter.** Follow steps 1 and 2 in the release README's **Run** section, replacing `ARCHIVE_SHA256`, `STARTER_SHA256` and `MANIFEST_SHA256` with the values published on the release page. Use the complete command blocks: they verify the downloaded files and installation directories before extracting the root-owned package into `/opt/ndx12`, installing the separate starter in `/usr/local/libexec/ndx12_start.py`, and recording the trusted manifest hash in `/etc/ndx12/v21.manifest.sha256`. Stop if either block reports `STOPPED`.

4. **Start through the external starter**, including on every later run. For the v21 package:

   ```sh
   sudo /usr/bin/python3 -I -B /usr/local/libexec/ndx12_start.py \
     --package /opt/ndx12/ndx12-native-benchmark-v21-615.78.08-620.70.06 \
     --trust /etc/ndx12/v21.manifest.sha256
   ```

   Use the matching package and trust-file paths from your release README. Keep the terminal open for the whole run. Do not suspend or log out.

5. **Pass the checks.** Before it runs the launcher, the starter checks the package against the trusted manifest hash, verifies its files and checks ownership and permissions. It prints **PACKAGE VERIFIED** on success. You can append `--check-only` to the command above to check the installation without starting the benchmark. The launcher then checks the GPU, driver and requirements. If it prints **CANNOT RUN ON THIS COMPUTER**, it lists the reasons and starts no benchmark work. Otherwise, read the warning and type `run`.

6. **Choose the tests.** Press Enter for the **Full test**, or select the compute suite, Test 1 (D4), Test 2 (K) or Test 3 (K WaveForm) separately.

7. **Choose the clocks.** For a first run, choose **1: keep your current clock settings**. Clock locking is optional. The built-in presets apply only to the GPU models they are named for: RTX 4090 and RTX 3090.

8. **Open the results.** When the run finishes, open the `charts.html` path printed under **CHARTS**.

9. **Share your results.** [Open a GitHub issue](https://github.com/GoblinFlash/Native-DX12-Linux/issues) and include your GPU model, NVIDIA driver version and result charts. The launcher also prepares `share-results.tar.gz`, containing the results intended for sharing. **SEND THIS FILE** is the terminal label identifying that archive; nothing is sent automatically.

If you started the launcher with `sudo` from your normal account, a copy of the charts page and share bundle is also placed in `~/ndx12-results/<run folder>/`.

The full raw evidence stays in `/var/tmp/ndx12-results/`. **It contains machine identifiers, so keep it private.**

**If something goes wrong:** if the launcher reports **HELD** or an unknown GPU-worker state, do not start another run. Keep the message shown on screen and follow the troubleshooting section of the package README. The benchmark never resets the GPU or retries on its own.
