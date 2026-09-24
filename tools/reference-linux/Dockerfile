# Reference Linux for real example outputs of the command catalog.
# Same release as the learner WSL (Ubuntu 24.04). Build once:
#   docker build -t cyber-range-coach-reference:24.04 tools/reference-linux
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive TZ=Asia/Almaty LANG=C.UTF-8
# Keep man pages and docs: the catalog teaches `man`.
RUN rm -f /etc/dpkg/dpkg.cfg.d/excludes && \
    apt-get update && apt-get install -y --no-install-recommends \
      coreutils findutils grep sed gawk diffutils procps psmisc iproute2 less file \
      util-linux mount acl sudo cron tzdata passwd man-db manpages \
      xxd binutils nano openssh-server openssh-client netcat-openbsd nmap curl \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*
# The minimized base image diverts man to a stub that prints "unminimize".
# The learner WSL Ubuntu is not minimized, so restore the real man.
RUN if [ -f /usr/bin/man.REAL ]; then \
      rm /usr/bin/man && dpkg-divert --quiet --remove --rename /usr/bin/man; \
    fi && mandb -q
