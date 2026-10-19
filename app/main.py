from fastapi import FastAPI

app = FastAPI(title="MacroPal API")

@app.get("/")
def root():
    return {
        "name": "MacroPal API",
        "status": "online"
    }