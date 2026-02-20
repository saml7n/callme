from fastapi import FastAPI

app = FastAPI(title="CallMe", description="AI Receptionist Server")


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}
