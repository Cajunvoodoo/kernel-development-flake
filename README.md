# Kernel Development Flake

A nix flake dedicated to making the developer tooling around kernel development
(both in-tree and out-of-tree) easier. Add this flake as an input, and use the
provided scripts, the 'kdf' cli, and builder functions.

## Features

* Compile a minimal kernels designed for debugging using nix.
  * Rust support by default.
* Nix builders for Rust and C kernel modules
* The 'kdf' cli for running a VMs with ultra-fast boot times with access to the
  host file system for development.
  * Powered by 'kdf-init', a small rust '/init' inspired by
    [virtme-ng](https://github.com/arighi/virtme-ng).
* Run VMs
* Remote GDB debugging through the VM
* Out of tree rust-analyzer support

## Cloning the flake

While the recommended way to get started is to use this flake as an input. You
can try out all the features by cloning this repository.

### kdf CLI

Run a VM for live-development which is powered by virtiofs mounts and the
minimal 'kdf-init'.

Enter the devshell with 'direnv allow' or 'nix develop .#'.

Startup the VM with `just run`. This drop you into a shell with the current
working directory mounted into the VM. Uses 'kdf run' under the hood. Edit and
recompile modules on the host with built module being available inside the VM.

To debug just call `just debug` which will attach a debugger to the VM. Call
`lx-symbols-runtime` to load symbols for the kernel modules.

### Nix-based VM

This is a nix-built reproducible VM image that includes the nix-built kernel
modules.  Along with a GDB helper.

Get the '.#runQemu' and '.#runGdb' outputs into your path.

Run `runvm` to run QEMU (uses sudo for enabling kvm). Inside qemu the nix-built
kernel modules are available in the 'modules/' directory.

Run `rungdb` to attach to the QEMU VM with all the correct source paths
loaded. Run `lx-symbols-nix` in GDB to get symbols of the modules.

## Flake as an input

The `lib.builders` output of the flake exposes all the components as Nix builder
functions. You can use them to compile your own kernel, configfile, initramfs,
and generate the `runvm` and `rungdb` commands. An example of how the functions
are used is below. See the `flake.nix` file for more details, and the `build`
directory for the arguments that can be passed to the builders.

There is also the 'kdf' CLI which is recommended for live development. It is
currently under documented. See the `justfile` and `just {run/debug}` for an
example of how to use. You will want to add your own helper similar to `just
run` that uses the CLI parameters to setup the VM. E.g. if developing in-tree,
using a minimal nix-built kernel, or just pulling one from nixpkgs with `-r`.

```nix
{
   inputs.kernelFlake.url = "github:jordanisaacs/kernel-module-flake";

   outputs =  {
     self,
     nixpkgs,
     kernelFlake
   }: let
     system = "x86_64-system";
     pkgs = nixpkgs.legacyPackages.${system};

     kernelLib = kernelFlake.lib.builders {inherit pkgs;};

     buildRustModule = buildLib.buildRustModule {inherit kernel;};
     buildCModule = buildLib.buildCModule {inherit kernel;};

     configfile = buildLib.buildKernelConfig {
       generateConfigFlags = {};
       structuredExtraConfig = {};

       inherit kernel nixpkgs;
     };

     kernel = buildLib.buildKernel {
       inherit configfile;

       src = ./kernel-src;
       version = "";
       modDirVersion = "";
     };

     modules = [exampleModule];

     initramfs = buildLib.buildInitramfs {
       inherit kernel modules;
     };

     exampleModule = buildCModule { name = "example-module"; src = ./.; };

     runQemu = buildLib.buildQemuCmd {inherit kernel initramfs;};
     runGdb = buildLib.buildGdbCmd {inherit kernel modules;};
   in { };
}
```

## How it works

### kdf Cli

#### Initramfs

A tiny static `/init` (see 'kdf-init') that mounts essential kernel filesystems,
loads any provided kernel modules, mounts host filesystems using virtiofs, then
runs the user provided command.

Can build using `kdf build initramfs`. Under the hood, automatically builds an
initramfs if running a VM using `kdf run -r` and adds the kernel modules needed
from the nix linux package.

#### QEMU VM

The `kdf run` command automatically uses the built `/init`/initramfs which is
pre-packaged. It handles the lifetime of the required `virtiofsd` instances.

There is a helper provided `--nix` that will mount the '/nix/store' for you and
evaluate/add the bin paths to your `PATH`.

### Nix Builds

#### Linux Kernel

A custom kernel is built according to Chris Done's [Build and run minimal Linux / Busybox systems in Qemu](https://gist.github.com/chrisdone/02e165a0004be33734ac2334f215380e). Extra config is added which I got through Kaiwan Billimoria's [Linux Kernel Programming](https://www.packtpub.com/product/linux-kernel-programming/9781789953435).

First a derivation is built for the `.config` file.  It is generated using a modified version of the `configfile` derivation in the [generic kernel builder](https://github.com/NixOS/nixpkgs/blob/nixos-unstable/pkgs/os-specific/linux/kernel/generic.nix) (also known as the `buildLinux` function). This modified derivation is required to remove the NixOS distribution default configuration. More documentation is in the `build/c-module.nix` the flake.

Compiling the kernel is the same as `Nix` but modified to not remove any of the source files from the dev output. This is because they are necessary for things such as gdb debugging, and rust development.

Then a new package set called `linuxDev` is then added as an overlay using `linuxPackagesFor`.

#### Rust Support

Rust support is enabled by using the default configuration with `enableRust = true`, or setting `RUST = true` in the kernel configuration. The build will automatically pick up up the value set in the kernel config and build correctly.

#### Kernel Modules

The kernel modules are built using nix. You can build them manually with `nix build .#helloworld` and `nix build .#rust`. They are copied into the initramfs for you. There is a `buildCModule` and `buildRustModule` function exposed for building your own modules (`build/rust-module.nix` and `build/c-module.nix`).

#### eBPF Support

eBPF is enabled by default. This makes the initrd much larger due to needing python for `bcc`, and the compile time of the linux kernel longer. You can disable it by setting `enableBPF = false` in `flake.nix`.

#### initramfs

The initial ram disk is built using the new [make-initrd-ng](https://github.com/NixOS/nixpkgs/tree/master/pkgs/build-support/kernel/make-initrd-ng). It is called through its [nix wrapper](https://github.com/NixOS/nixpkgs/blob/master/pkgs/build-support/kernel/make-initrd-ng.nix) which safely copies the nix store packages needed over. To see how to include modules and other options see the builder, `build/initramfs.nix`.

#### GDB

Remote GDB debugging is activated through the `rungdb` command (`build/run-gdb.nix`). It wraps GDB to provide the kernel source in the search path, loads `vmlinux`, sources the kernel gdb scripts, and then connects to the VM. An alias is provided `lx-symbols-nix` that runs the `lx-symbols` command with all the provided modules' nix store paths as search directories.

### Editor

How to get language servers working.

#### C

Clang-format was copied over from the linux source tree. To get CCLS working correctly call `bear -- make` to get a `compile_commands.json`. Then open up C files in your favorite editor with an LSP set up.

#### Rust

The flake is configured to build the kernel with a `rust-project.json` but it is not usable to out of tree modules. A script is run that parses the kernel's `rust-project.json` and generates one for the module itself. It is accessed with `make rust-analyzer`. Credit to thepacketgeek for the [script](https://github.com/Rust-for-Linux/rust-out-of-tree-module/pull/2). Additionally, rust-analyzer is designed to use `cargo check` for diagnostics. There is an opt-out to use rustc outputs which is configured within the editor's rust-analyzer configuration.

The rust-analyzer options should be look something along the lines of:

```nix
let
  cmd =
    writeShellScript
    "module-ra-check"
    ''make -s "KRUSTFLAGS+=--error-format=json" 2>&1 | grep -v "^make"'';
in ''
  ["rust-analyzer"] = {
    cargo = {
      buildScripts = {
        overrideCommand = {"${cmd}"},
      },
    },
    checkOnSave = {
      overrideCommand = {"${cmd}"},
    },
  },
'';
```

### Direnv

If you have nix-direnv enabled a shell with everything you need should open when you `cd` into the directory after calling `direnv allow`
