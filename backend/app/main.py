from fastapi import FastAPI

app = FastAPI(title="AI Car Matchmaker")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
