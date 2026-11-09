# How to run

These instructions are for release v0.1.0 of the benchmark. Its package keeps its internal name, `ndx12-native-benchmark-v21-615.78.08-620.70.06`. Running `git clone` downloads the source repository; it does not install the benchmark.

1. **Prepare the machine.** Save your work and close games and other GPU-heavy programs; a driver fault may freeze the display. Do not change your driver just for this test. `/usr/bin/python3` must be standard CPython 3.13 or newer with the GIL enabled; the installer checks it. To start the benchmark from your normal account, `/usr/bin/sudo` must be available.

2. **Download three files into one new folder.**
   - `ndx12-install.py`: the installer, from the `NDX12_GPU_Benchmark` folder of this repository at tag `v0.1.0`.
   - `ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz`: the benchmark archive, from release v0.1.0.
   - `ndx12_start.py`: the starter, from release v0.1.0.

   You can use your browser. If you have `curl`, this downloads all three files into a new folder:

   ```sh
   mkdir ndx12-v0.1.0 && cd ndx12-v0.1.0 &&
   curl -fLO https://raw.githubusercontent.com/GoblinFlash/Native-DX12-Linux/v0.1.0/NDX12_GPU_Benchmark/ndx12-install.py &&
   curl -fLO https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.0/ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz &&
   curl -fLO https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.0/ndx12_start.py
   ```

   You do not need to copy any checksum. See [Where the trust comes from](#where-the-trust-comes-from).

3. **Install.** In that folder, run:

   ```sh
   sudo /usr/bin/python3 -I ndx12-install.py
   ```

   Type it as shown: the installer refuses to run without `-I` or with a Python other than `/usr/bin/python3`.

   It checks:
   - that both downloaded files are the ones it was made for;
   - that the system folders it writes to belong to root and only root can change them;
   - that nothing it would replace is a symbolic link.

   It then installs:
   - the package into `/opt/ndx12`;
   - the starter as `/usr/local/libexec/ndx12_start.py`;
   - the trusted manifest value as `/etc/ndx12/v21.manifest.sha256`;
   - the command `/usr/local/bin/ndx12-benchmark`.

   It has the starter verify the package, and finishes with **READY**.

   If it prints **NOT INSTALLED**, it says what blocks the installation and what to change. A refusal leaves an installed copy as it was. Fix the problem and run the same command again. If a failure happens while installed files are being replaced, it says that the installation is incomplete; running it again completes it.

   You can run the installer again at any time:
   - An installed package that still verifies is kept, together with its saved settings.
   - A copy that no longer verifies is moved aside to `/opt/ndx12/ndx12-native-benchmark-v21-615.78.08-620.70.06.replaced-<time>`. You can remove it once you no longer need it.

   The installer never starts the benchmark or any GPU work.

4. **Start the benchmark**, now and on every later run:

   ```sh
   ndx12-benchmark
   ```

   The benchmark runs as root, so `sudo` asks for your password. Keep the terminal open for the whole run. Do not suspend or log out.

   - `ndx12-benchmark --check` checks the installation only and starts nothing.
   - `ndx12-benchmark -- ARGS` passes `ARGS` to the package's `run_benchmark.sh`. These are the expert options in the package README.

5. **Pass the checks.** Before anything from the package runs, the starter checks:
   - the package against the trusted manifest value;
   - every file in the package;
   - the ownership and permissions of the package and the folders above it.

   It prints **PACKAGE VERIFIED** on success. The launcher then checks the GPU, the driver and the other requirements. If it prints **CANNOT RUN ON THIS COMPUTER**, it lists the reasons and starts no benchmark work. Otherwise, read the warning and type `run`.

6. **Choose the tests.** Press Enter for the **Full test**, or select one of these separately:
   - the compute suite;
   - Test 1 (D4);
   - Test 2 (K);
   - Test 3 (K WaveForm).

7. **Choose the clocks.** For a first run, choose **1: keep your current clock settings**. Clock locking is optional. The built-in presets apply only to the GPU models they are named for: RTX 4090 and RTX 3090.

8. **Open the results.** When the run finishes, open the `charts.html` path printed under **CHARTS**.

9. **Share your results.** [Open a GitHub issue](https://github.com/GoblinFlash/Native-DX12-Linux/issues) and include your GPU model, NVIDIA driver version and result charts. The launcher also prepares `share-results.tar.gz`, which holds the results intended for sharing. **SEND THIS FILE** is the terminal label identifying that archive; nothing is sent automatically.

When you start `ndx12-benchmark` from your normal account, a copy of the charts page and share bundle is also placed in `~/ndx12-results/<run folder>/`.

The full raw evidence stays in `/var/tmp/ndx12-results/`. **It contains machine identifiers, so keep it private.**

**If something goes wrong:** if the launcher reports **HELD** or an unknown GPU-worker state, do not start another run. Keep the message shown on screen and follow the troubleshooting section of the package README. The benchmark never resets the GPU or retries on its own.

## Where the trust comes from

**The installer is what you trust.** It is a file in this repository, `NDX12_GPU_Benchmark/ndx12-install.py`, with a public change history. It contains three values for this release:
- the SHA-256 and size of the archive;
- the SHA-256 and size of the starter;
- the SHA-256 of the archive's `MANIFEST.sha256`.

**The archive and the starter are only checked.** They come from the release, and the installer refuses them unless they match those values exactly. A replaced or damaged file is refused, wherever it was downloaded from; a copy from another place is accepted only if its bytes are identical. The starter then checks the installed package against the manifest value before every start, so a later change inside the package is also refused.

**What this does not protect against.** Someone who can change this repository, for example through a compromised maintainer account, can change the installer and its values together. There is no signature. To check the installer yourself:
- read it (it is one short Python file);
- compare it with its history in the repository.

A checksum file downloaded next to the archive, or a checksum you calculate from your own download, is not an independent check. The installer does not use either.

**One installer per release.** This installer installs only release v0.1.0, which is the package `ndx12-native-benchmark-v21-615.78.08-620.70.06`. A new release comes with a new installer.

## Without the installer

The manual steps in the **Run** section of the package README still work and install the same files. In that case:
- take the three values from the `ARCHIVE_SHA256`, `STARTER_SHA256` and `MANIFEST_SHA256` lines of `ndx12-install.py`;
- start the benchmark with the long `ndx12_start.py` command from that section, since `ndx12-benchmark` is installed only by the installer.

If you installed this package earlier with those steps, run the installer once. It keeps your installed package if it verifies and adds the `ndx12-benchmark` command.

## Removing it

```sh
sudo rm -r /opt/ndx12/ndx12-native-benchmark-v21-615.78.08-620.70.06 /usr/local/libexec/ndx12_start.py \
  /etc/ndx12/v21.manifest.sha256 /usr/local/bin/ndx12-benchmark
```

This keeps your results in `/var/tmp/ndx12-results/` and `~/ndx12-results/`.
