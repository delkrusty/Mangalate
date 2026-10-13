"""Hardware-neutral discovery. A detected GPU does NOT prove model compatibility."""
import os
import platform
import shutil
from pathlib import Path


def detect(system=None, kfd=None, nvidia=None):
    system = system or platform.system()
    kfd = Path("/dev/kfd").exists() if kfd is None else kfd
    nvidia = shutil.which("nvidia-smi") is not None if nvidia is None else nvidia
    backends = [
        {"id": "cpu", "state": "available", "reason": "Baseline sem GPU; depende de RAM e pacotes para a arquitetura."},
        {"id": "gpu", "state": "candidate" if nvidia else "not_detected",
         "reason": "CUDA/NVIDIA exige teste do driver, Container Toolkit e modelos."},
        {"id": "amd-rocm", "state": "experimental_candidate" if system == "Linux" and kfd else "not_detected",
         "reason": "ROCm requer Linux, placa compatível e /dev/kfd + /dev/dri; ainda não validado em hardware AMD neste pacote."},
        {"id": "directml", "state": "planned",
         "reason": "Windows AMD/Intel/NVIDIA: exige adaptar e validar as etapas ONNX. Não é ativado neste backend PyTorch."},
        {"id": "openvino", "state": "planned",
         "reason": "Intel CPU/iGPU/Arc/NPU: requer modelos exportados e testes por etapa; use CPU enquanto isso."},
    ]
    return {"os": system, "architecture": platform.machine(), "safe_default": "cpu", "backends": backends}


if __name__ == "__main__":
    import json
    print(json.dumps(detect(), ensure_ascii=False, indent=2))
