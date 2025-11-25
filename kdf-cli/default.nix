{
  pkgs,
  lib,
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
  kdf-init,
}:

let
  # Load the workspace from uv.lock
  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

  # Create the overlay
  overlay = workspace.mkPyprojectOverlay {
    sourcePreference = "wheel";
  };

  # Build Python set with overlay
  pythonSet = (pkgs.callPackage pyproject-nix.build.packages {
    python = pkgs.python3;
  }).overrideScope (
    lib.composeManyExtensions [
      pyproject-build-systems.overlays.default
      overlay
    ]
  );

  # Get mkApplication utility
  inherit (pkgs.callPackage pyproject-nix.build.util { }) mkApplication;

  # Build the virtual environment with the package
  venv = pythonSet.mkVirtualEnv "kdf-cli-env" workspace.deps.default;

  # Create the application (unwrapped)
  app = mkApplication {
    inherit venv;
    package = pythonSet.kdf-cli;
  };

  # Stage 1: Unwrapped kdf-cli with just PATH dependencies for building initramfs
  unwrapped = pkgs.runCommand "kdf-cli-unwrapped"
    {
      nativeBuildInputs = [ pkgs.makeWrapper ];
    }
    ''
      mkdir -p $out/bin
      cp -r ${app}/* $out/

      # Wrap with minimal dependencies needed for initramfs build
      wrapProgram $out/bin/kdf \
        --prefix PATH : ${lib.makeBinPath [
          pkgs.coreutils
          pkgs.xz
          pkgs.gzip
          pkgs.cpio
          pkgs.findutils
          pkgs.kmod
        ]}
    '';
in
# Stage 2: Build prebuilt initramfs and wrap with full runtime dependencies
pkgs.runCommand "kdf-cli"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta = app.meta // {
      description = "Kernel development flake - Manage kdf-init initramfs and kernel execution";
      license = lib.licenses.mit;
      mainProgram = "kdf";
    };
  }
  ''
    mkdir -p $out/bin
    mkdir -p $out/share/kdf

    # Copy the unwrapped application
    cp -r ${app}/* $out/

    # Copy kdf-init binary to resource directory
    cp ${kdf-init}/bin/init $out/share/kdf/init

    # Build prebuilt initramfs using the unwrapped kdf-cli
    ${unwrapped}/bin/kdf build initramfs ${kdf-init}/bin/init \
      --output $out/share/kdf/initramfs.cpio

    # Wrap the binary with full runtime dependencies and resource path
    wrapProgram $out/bin/kdf \
      --prefix PATH : ${lib.makeBinPath [
        pkgs.qemu
        pkgs.virtiofsd
        pkgs.coreutils
        pkgs.xz
        pkgs.gzip
        pkgs.cpio
        pkgs.findutils
        pkgs.kmod
      ]} \
      --set KDF_RESOURCE_DIR $out/share/kdf
  ''
