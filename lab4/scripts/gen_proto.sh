#!/usr/bin/env sh
# Пересборка snakes_game/proto/snakes_pb2.py из proto/snakes.proto.
# Версия grpcio-tools закреплена, чтобы сгенерированный код работал с protobuf >= 4.25.
set -e
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc -I proto --python_out=snakes_game/proto proto/snakes.proto
echo "ok: snakes_game/proto/snakes_pb2.py"
