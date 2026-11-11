# SPDX-License-Identifier: GPL-3.0-or-later
# 可选：自行构建渲染镜像。仓库不发布预构建镜像，避免 GPL 分发义务与黑盒问题。
#
#   docker build -t blender-gpu docker/
#
# 注意：BLENDER_VERSION 必须与你服务器上的 Blender 版本一致，
# 否则 .blend 可能无法打开（高版本存的文件低版本读不了）。

FROM ubuntu:22.04

ARG BLENDER_SERIES=5.2
ARG BLENDER_VERSION=5.2.0

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils \
        libxi6 libxxf86vm1 libxfixes3 libxrender1 libgl1 libsm6 \
        libxkbcommon0 libegl1 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL \
        "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        -o /tmp/blender.tar.xz \
    && mkdir -p /opt/blender \
    && tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && rm /tmp/blender.tar.xz \
    && ln -s /opt/blender/blender /usr/local/bin/blender

WORKDIR /work
ENTRYPOINT ["blender"]
