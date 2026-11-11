# How to run

## Download v0.1.5

**[Open release v0.1.5](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.5)**

Download these **three files into the same new folder**:

1. **[Installer — ndx12-install.py](https://raw.githubusercontent.com/GoblinFlash/Native-DX12-Linux/v0.1.5/NDX12_GPU_Benchmark/ndx12-install.py)** — save the linked file if your browser displays its contents.
2. **[Benchmark archive — .tar.gz](https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.5/ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz)**
3. **[Starter — ndx12_start.py](https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.5/ndx12_start.py)**

The source archives are for developers; you do not need them to run the benchmark. Follow the installation steps below.

These links require the matching tag and release assets. If they are not available, use [v0.1.4 and its tagged instructions](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.4/NDX12_GPU_Benchmark/HOW_TO_RUN.md). Do not mix files from different releases.

## Install and run

These instructions are for release v0.1.5 of the benchmark. Its package keeps its internal name, `ndx12-native-benchmark-v21-615.78.08-620.70.06`. Running `git clone` downloads the source repository; it does not install the benchmark.

1. **Prepare the machine.** Save your work and close games and other GPU-heavy programs; a driver fault may freeze the display. Do not change your driver just for this test. `/usr/bin/python3` must be standard CPython 3.13 or newer with the GIL enabled; the installer checks it. To start the benchmark from your normal account, `/usr/bin/sudo` must be available.

2. **Download three files into new folder.**
   - `ndx12-install.py`: the installer, from the `NDX12_GPU_Benchmark` folder of this repository at tag `v0.1.5`.
   - `ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz`: the benchmark archive, from release v0.1.5.
   - `ndx12_start.py`: the starter, from release v0.1.5.

   You can use your browser. If you have `curl`, this downloads all three files into a new folder:

   ```sh
   mkdir ndx12-v0.1.5 && cd ndx12-v0.1.5 &&
   curl -fLO https://raw.githubusercontent.com/GoblinFlash/Native-DX12-Linux/v0.1.5/NDX12_GPU_Benchmark/ndx12-install.py &&
   curl -fLO https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.5/ndx12-native-benchmark-v21-615.78.08-620.70.06.tar.gz &&
   curl -fLO https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.5/ndx12_start.py
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
   - the command `/usr/local/bin/ndx12-benchmark`;
   - the install receipt `/etc/ndx12/ndx12-native-benchmark-v21-615.78.08-620.70.06.install.json`. It records the release name and the values the installer checked. The benchmark reads it to name the release in your share file.

   It has the starter verify the package, and finishes with **READY**.

   If it prints **NOT INSTALLED**, it says what blocks the installation and what to change. A refusal before replacement leaves an installed copy as it was. If replacement and restoration both fail, it reports an incomplete installation and the exact folder where the previous package remains. Keep that folder; a later successful installation does not delete it. Resolve the reported file-operation error before retrying.

   You can run the installer again at any time:
   - An installed package that still verifies is kept, together with its saved settings.
   - A copy that no longer verifies is moved aside to `/opt/ndx12/ndx12-native-benchmark-v21-615.78.08-620.70.06.replaced-<time>`. You can remove it once you no longer need it.
   - Releases v0.1.0 to v0.1.4 use the same package folder. Their packages do not verify against this release's manifest value, so they are moved aside in the same way.

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

9. **Share your results.** [Submit benchmark results](https://github.com/GoblinFlash/Native-DX12-Linux/issues/new?template=benchmark_results.yml) using the short form. Include your benchmark version, GPU model, NVIDIA driver version and whether the run completed. The launcher also prepares `share-results-v0.1.5.tar.gz`, which holds the results intended for sharing. Its name says which release made it (`share-results-release-unknown.tar.gz` when the install receipt could not be checked). **SEND THIS FILE** is the terminal label identifying that archive; nothing is sent automatically. Inspect the bundle before attaching it and remove private information. Issues and attachments are public and linked to your GitHub account.

   When at least one chart is in the file, it also holds `charts.html`, the charts page made from those chart images; open it in a browser. A file without a chart has no `charts.html`. The header of every chart names the release, the OS, the GPU model and the driver. The `summary.txt` in the bundle names the release, the GPU model and driver, and the result of every process, and says whether the GPU timer ticks could be read as nanoseconds in your run. It contains no computer name, user name, IP address, GPU serial number or GPU UUID. Look inside before you post it.

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

**One installer per release.** This installer installs only release v0.1.5, which is the package `ndx12-native-benchmark-v21-615.78.08-620.70.06` (revision v21-r16). A new release comes with a new installer.

## Without the installer

The manual steps in the **Run** section of the package README still work and install the same files. In that case:
- take the three values from the `ARCHIVE_SHA256`, `STARTER_SHA256` and `MANIFEST_SHA256` lines of `ndx12-install.py`;
- start the benchmark with the long `ndx12_start.py` command from that section, since `ndx12-benchmark` is installed only by the installer.

Without the install receipt, your share file says `Release: unknown - NO_INSTALL_RECEIPT`.

If you installed this package earlier with those steps, run the installer once. It keeps your installed package if it verifies, and adds the `ndx12-benchmark` command and the install receipt.

## Removing it

```sh
sudo rm -r /opt/ndx12/ndx12-native-benchmark-v21-615.78.08-620.70.06 /usr/local/libexec/ndx12_start.py \
  /etc/ndx12/v21.manifest.sha256 /usr/local/bin/ndx12-benchmark \
  /etc/ndx12/ndx12-native-benchmark-v21-615.78.08-620.70.06.install.json
```

This keeps your results in `/var/tmp/ndx12-results/` and `~/ndx12-results/`.
