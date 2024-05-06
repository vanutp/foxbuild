{
  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = import nixpkgs {inherit system;};
      in {
        packages.default = pkgs.buildEnv {
          name = "foxbuild-env";
          paths = with pkgs; [
            bind
            iproute2
            iputils
            nettools
            nix
            nix-info
            nix-bash-completions
            dbus
            iptables
            bashInteractive
            nano
            less
            shared-mime-info
            acl
            attr
            bzip2
            coreutils-full
            curl
            diffutils
            findutils
            gawk
            glibc
            getent
            getconf
            gnugrep
            patch
            gnused
            gnutar
            gzip
            xz
            libcap
            ncurses
            libressl
            cacert
            openssh
            mkpasswd
            procps
            time
            util-linux
            which
            zstd
            perl
            rsync
            strace
            glibcLocales
            git
            (writeShellScriptBin "bwrap-wrapper" ''
              set -euo pipefail

              UID_=$1
              shift
              GID_=$1
              shift
              DO_OVERLAY=$1
              shift

              if [[ $DO_OVERLAY = True ]]; then
                TARGET=/home/build/.cache/nix
                TEMPDIR="$(mktemp -d)"
                mkdir -p "$TEMPDIR"/{upper,work}
                mount -t overlay -o lowerdir="$TARGET",upperdir="$TEMPDIR"/upper,workdir="$TEMPDIR"/work none "$TARGET"
                trap 'umount "$TARGET" && rm -rf "$TEMPDIR"' EXIT
              fi

              chown -R build:users /home/build
              (cd "$(pwd)" && capsh --drop=CAP_SYS_ADMIN --drop=CAP_SETPCAP --drop=CAP_DAC_OVERRIDE --drop=CAP_SETUID --drop=CAP_SETGID --gid=$GID_ --uid=$UID_ --caps="" --shell=/usr/bin/env -- -- "$@")
              ''
            )
            (writeTextFile {
              name = "nix.conf";
              destination = "/etc/nix/nix.conf";
              text = ''
                experimental-features = nix-command flakes repl-flake
                trusted-users = root
              '';
            })
            (writeTextFile {
              name = "resolv.conf";
              destination = "/etc/resolv.conf";
              text = ''
                nameserver 1.1.1.1
              '';
            })
            (writeTextFile {
              name = "passwd";
              destination = "/etc/passwd";
              text = ''
                root:x:0:0:System administrator:/root:/profile/bin/nologin
                build:x:1000:100::/home/build:/profile/bin/bash
                nobody:x:65534:65534:Unprivileged account (don't use!):/var/empty:/profile/bin/nologin
              '';
            })
            (writeTextFile {
              name = "group";
              destination = "/etc/group";
              text = ''
                root:x:0:
                users:x:100:
                nogroup:x:65534:
              '';
            })
            (writeTextFile {
              name = "shadow";
              destination = "/etc/shadow";
              text = ''
                root:!:1::::::
                build:!:1::::::
                nobody:!:1::::::
              '';
            })
            (runCommandLocal "certs" {} ''
              mkdir -p $out/etc/ssl/certs
              ln -s ${cacert}/etc/ssl/certs/ca-bundle.crt $out/etc/ssl/certs/ca-certificates.crt
            '')
          ];
        };
      }
    );
}
