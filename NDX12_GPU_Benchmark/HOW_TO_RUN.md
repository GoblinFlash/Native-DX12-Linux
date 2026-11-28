# How to run

## Download v0.1.9

**[Open release v0.1.9](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.9)**

Download the single-file installer:

**[NDX12-Benchmark-v0.1.9.run](https://github.com/GoblinFlash/Native-DX12-Linux/releases/download/v0.1.9/NDX12-Benchmark-v0.1.9.run)**

No separate benchmark archive, Python installer or starter is required. Running `git clone` downloads the source repository; it does not install the benchmark.

## Install and run

1. **Prepare the machine.** Save your work and close games and other GPU-heavy programs before benchmarking. A driver fault can freeze the display. Use an admitted NVIDIA GPU and driver; see [Hardware and requirements](README.md#hardware-and-requirements). The installer requires Linux x86-64, glibc 2.34 or newer, system Python 3.9 or newer, Bash and Polkit. The application includes its own Python and Qt.

2. **Download the installer.** Save the .run file from the release above. Optionally compare its SHA-256 with the value on the release page before running it:

   ```sh
   sha256sum NDX12-Benchmark-v0.1.9.run
   ```

   Expected SHA-256: `48c62aa693bcc1e146148976cd6917d3bc1acd8e4abf533d9bbb3cb8a3822c21`.

3. **Install.** Open a terminal in the download folder, from your normal desktop account, and run:

   ```sh
   sudo bash NDX12-Benchmark-v0.1.9.run
   ```

   The installer checks its embedded files, installs the application and configures the desktop entry and authorization for the account invoking sudo. It does not start GPU work. Use the same command with a newer installer to update. The installer retains the replaced package and configuration and restores the previous active installation if activation fails.

4. **Start the benchmark.** Open **Native DX12 Benchmark** from the desktop icon or application menu. Alternatively, run the following as your normal desktop user:

   ```sh
   ndx12-benchmark
   ```

   `ndx12-benchmark --check` performs a CPU-only integrity check. It does not run the benchmark.

5. **Choose the tests.** On the Benchmark page, choose **Full Benchmark** or select individual workloads. Enable the separate Vulkan reference if you want the comparison for supported workloads. The launcher checks the GPU and driver before starting work.

6. **Choose the clocks.** Keep your current clock settings for a first run. Reference profiles and manual frequencies are optional and depend on the GPU and driver.

7. **Start the run.** Click **Run Full Benchmark (recommended)** or run the selected workloads. Do not suspend or log out while a run is active.

8. **Open the results.** Review the integrated charts and Run log. **Result files** opens the exported results folder.

9. **Share your results.** Click **Share Results** next to **Run log** to open the public GitHub form, or [submit benchmark results](https://github.com/GoblinFlash/Native-DX12-Linux/issues/new?template=benchmark_results.yml) manually and attach the exported `share-results-*.tar.gz` file. Include the benchmark version, GPU, driver, Linux distribution and run outcome.

   Chrome or Chromium uses a separate sharing profile and can upload the archive when opening the form. In other browsers, attach the archive from **Result files** manually. Review the form and choose **Create issue** to publish it. Check the archive for private information first. Issues and attachments are public.

## Graphics demos

Open **Demos**, select Earth 4K, nBody 128, nBody 10K or nBody 4K, then click **Launch Demo**. The native demo uses the admitted GPU/driver profile and its available desktop presentation path. Do not start a second demo or another benchmark while GPU work from this application is active.

## Troubleshooting

Start the launcher from your normal desktop account (without sudo):

```sh
ndx12-benchmark --debug
```

The terminal displays live Run log messages, process output, launch commands and exit codes. Diagnostics, Bug Report, Live Output and Saved Reports are also available under GPU Monitoring. Inspect diagnostic reports and attachments for private information before sharing.

If the launcher reports **HELD** or an unknown GPU-worker state, do not start another run. Preserve the error message and report it through Issues. v0.1.9 cleans up certain allocation refusals before GPU work starts; other faults can still leave resources held deliberately. Follow the [current release limits](https://github.com/GoblinFlash/Native-DX12-Linux/releases/tag/v0.1.9#validation-and-current-limits).

Share only the intended results archive. Full raw evidence in `/var/tmp/ndx12-results/` may contain machine identifiers; keep it private.

## Where the trust comes from

The release page records the installer size and SHA-256. The self-extracting installer checks the embedded installer, starter and benchmark archive against its internal size and SHA-256 values. The installed package is checked against its trusted manifest.

These checks identify the expected bytes; they do not protect against a compromised release publisher. Obtain the installer from the official release. Do not mix files from different versions.

## Removing it

Open **Uninstall Native DX12 Benchmark** from the application menu, or run:

```sh
sudo ndx12-uninstall
```

The uninstaller preserves the result folders and launcher settings. It refuses while a benchmark is running or an installation is pending.

## Previous releases

The old three-file instructions and standalone `ndx12-install.py` apply to v0.1.5, not v0.1.9. For the older release, use its [tagged instructions](https://github.com/GoblinFlash/Native-DX12-Linux/blob/v0.1.5/NDX12_GPU_Benchmark/HOW_TO_RUN.md) and matching assets.
