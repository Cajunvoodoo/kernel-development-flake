{
  writeScriptBin,
}:
{
  kernel,
  initramfs,
  memory ? "1G",
}:
writeScriptBin "runvm" ''
#! /usr/bin/env bash
  qemu-system-x86_64 \
    -enable-kvm \
    -m ${memory} \
    -kernel ${kernel}/bzImage \
    -initrd ${initramfs}/initrd.gz \
    -nographic -append "console=ttyS0" \
    -s
''
