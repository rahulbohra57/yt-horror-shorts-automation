# main.py — stub, full implementation comes in Task 9
from fastapi import FastAPI
app = FastAPI(title="YT Shorts Bot")

@app.get("/health")
def health():
    return {"status": "ok"}
