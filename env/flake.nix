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
            shadow
            (writeShellScriptBin "bwrap-wrapper" ''
              set -euo pipefail

              UID_=$1
              shift
              GID_=$1
              shift
              DO_OVERLAY=$1
              shift

              mkdir -p /etc
              if [[ ! -f /etc/passwd ]]; then
                cat /profile/etc/passwd > /etc/passwd
                cat /profile/etc/group > /etc/group
                cat /profile/etc/shadow > /etc/shadow
              fi
              if [[ ! -d /etc/ssl ]]; then
                ln -s /profile/etc/ssl /etc/ssl
              fi
              ln -s /profile/etc/nix /etc/nix
              if [[ -f /etc/defaults/useradd ]]; then
                rm /etc/defaults/useradd
              fi

              getent passwd | awk -F: "\$3 == $UID_ {print \$1}" | xargs -n1 -rd '\n' userdel --
              getent group | awk -F: "\$3 == $GID_ {print \$1}" | xargs -n1 -rd '\n' groupdel -f --
              if [ $(getent group users) ]; then
                groupdel -f users
              fi
              if [ $(getent passwd build) ]; then
                userdel build
              fi

              groupadd -g $GID_ users
              useradd -M -s /bin/sh -u $UID_ -g users build

              uid_count_1=$((UID_-1))
              uid_count_2=$((65536-UID_-1))
              uid_start_2=$((UID_+1))
              cat <<EOF >/etc/subuid
              build:1:$uid_count_1
              build:$uid_start_2:$uid_count_2
              EOF
              gid_count_1=$((GID_-1))
              gid_count_2=$((65536-GID_-1))
              gid_start_2=$((GID_+1))
              cat <<EOF >/etc/subgid
              build:1:$gid_count_1
              build:$gid_start_2:$gid_count_2
              EOF

              if [[ $DO_OVERLAY = True ]]; then
                TARGET=/home/build/.cache/nix
                TEMPDIR="$(mktemp -d)"
                mkdir -p "$TEMPDIR"/{upper,work}
                mount -t overlay -o lowerdir="$TARGET",upperdir="$TEMPDIR"/upper,workdir="$TEMPDIR"/work none "$TARGET"
                trap 'umount "$TARGET" && rm -rf "$TEMPDIR"' EXIT
              fi

              mkdir -p /home/build/.config/containers
              cat <<EOF > /home/build/.config/containers/containers.conf
              [containers]
              volumes = [
                      "/proc:/proc",
              ]
              default_sysctls = []
              EOF

              chown build:users /home/build
              chown -R build:users /home/build/{.cache,.config,.local}

              (cd "$(pwd)" && capsh --drop=CAP_SYS_ADMIN --gid=$GID_ --uid=$UID_ --caps="" --shell=/usr/bin/env -- -- "$@")
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
            (runCommandLocal "certs" {} ''
              mkdir -p $out/etc/ssl/certs
              ln -s ${cacert}/etc/ssl/certs/ca-bundle.crt $out/etc/ssl/certs/ca-certificates.crt
            '')
            (writeTextFile {
              name = "passwd";
              destination = "/etc/passwd";
              text = ''
                root:x:0:0:System administrator:/root:/profile/bin/nologin
                nobody:x:65534:65534:Unprivileged account (don't use!):/var/empty:/profile/bin/nologin
              '';
            })
            (writeTextFile {
              name = "group";
              destination = "/etc/group";
              text = ''
                root:x:0:
                nogroup:x:65534:
              '';
            })
            (writeTextFile {
              name = "shadow";
              destination = "/etc/shadow";
              text = ''
                root:!:1::::::
                nobody:!:1::::::
              '';
            })
          ];
        };
      }
    );
}
