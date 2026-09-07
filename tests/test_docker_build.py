import shutil
import subprocess
import pytest


@pytest.mark.skipif(shutil.which("docker") is None, reason="当前主机未安装 Docker；在 DS220+ 或 CI 执行")
def test_linux_amd64_image_builds():
    subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", "stock-agent:build-test", "."], check=True, timeout=1800)
