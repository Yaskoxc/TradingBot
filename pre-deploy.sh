#!/bin/bash
set -e

pip install --upgrade pip setuptools wheel

pip install Cython==3.0.8

python --version
pip --version