import json
import subprocess
import sys
import pandas as pd

def fetch(name: str, args: dict, timeout: int = 35) -> pd.DataFrame:
    result=subprocess.run([sys.executable,"-m","app.data.worker"],input=json.dumps({"name":name,"args":args}),capture_output=True,text=True,encoding="utf-8",timeout=timeout,check=True)
    marker="RESULT_JSON:"
    if marker not in result.stdout:
        raise ValueError("数据源没有返回可解析结果")
    return pd.DataFrame(json.loads(result.stdout.rsplit(marker,1)[1]))
