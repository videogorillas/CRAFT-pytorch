FROM nvidia/cuda:10.1-cudnn7-devel-ubuntu18.04

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    tzdata sudo vim less curl jq git ca-certificates apt-transport-https gnupg \
    wget software-properties-common apt-utils xz-utils build-essential

RUN add-apt-repository -y ppa:deadsnakes/ppa
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 python3-dev python3-virtualenv python3-opencv

RUN useradd -u 2001 -ms /bin/bash -d /home/ubuntu -G sudo ubuntu
RUN echo "ubuntu:123" | chpasswd

USER ubuntu
WORKDIR /home/ubuntu

ENV VIRTUAL_ENV=/home/ubuntu/venv
RUN python3.6 -m virtualenv --python=/usr/bin/python3.6 $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY --chown=ubuntu:ubuntu download.list download.list
RUN wget -c -i download.list

#RUN pip install torch-1.1.0-cp36-cp36m-linux_x86_64.whl \
#                torchvision-0.3.0-cp36-cp36m-linux_x86_64.whl
RUN tar xvf ffmpeg-4.1.4-amd64-static.tar.xz && test -x ffmpeg-4.1.4-amd64-static/ffmpeg
ENV PATH="/home/ubuntu/ffmpeg-4.1.4-amd64-static/:$PATH"

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

ENV CUDA_HOME="/usr/local/cuda/"

COPY --chown=ubuntu:ubuntu . .

