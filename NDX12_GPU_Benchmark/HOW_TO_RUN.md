# How to run

The instructions below apply to the benchmark release archive. Use the README and exact archive names shipped with your package. Running `git clone` downloads the source repository; it does not install the ready-to-run benchmark package.

1. **Download and verify.** Get the release archive together with its `.sha256` file and run `sha256sum -c` on that checksum file. Continue only if it reports `OK`.

2. **Prepare the machine.** Save your work and close games and other GPU-heavy programs; a driver fault may freeze the display. Do not change your driver just for this test.

3. **Extract as root.** Extract the archive with `sudo` into a root-owned directory such as `/opt/ndx12`. The release README will provide the exact command. The package must remain owned by root and writable only by root; the launcher checks this before starting.

4. **Start the launcher** from inside the extracted package directory:

   ```sh
   sudo ./run_benchmark.sh
   ```

   Keep the terminal open for the whole run. Do not suspend or log out.

5. **Pass the checks.** The launcher checks the GPU, driver and requirements first. If it prints **CANNOT RUN ON THIS COMPUTER**, it lists the reasons and starts no benchmark work. Otherwise, read the warning and type `run`.

6. **Choose the tests.** Press Enter for the **Full test**, or select the compute suite, Test 1 (D4), Test 2 (K) or Test 3 (K WaveForm) separately.

7. **Choose the clocks.** For a first run, choose **1: keep your current clock settings**. Clock locking is optional. The built-in presets apply only to the GPU models they are named for: RTX 4090 and RTX 3090.

8. **Open the results.** When the run finishes, open the `charts.html` path printed under **CHARTS**.

9. **Share your results.** [Open a GitHub issue](https://github.com/GoblinFlash/Native-DX12-Linux/issues) and include your GPU model, NVIDIA driver version and result charts. The launcher also prepares `share-results.tar.gz`, containing the results intended for sharing. **SEND THIS FILE** is the terminal label identifying that archive; nothing is sent automatically.

If you started the launcher with `sudo` from your normal account, a copy of the charts page and share bundle is also placed in `~/ndx12-results/<run folder>/`.

The full raw evidence stays in `/var/tmp/ndx12-results/`. **It contains machine identifiers, so keep it private.**

**If something goes wrong:** if the launcher reports **HELD** or an unknown GPU-worker state, do not start another run. Keep the message shown on screen and follow the troubleshooting section of the package README. The benchmark never resets the GPU or retries on its own.
