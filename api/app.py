from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/api/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
    except:
        data = (await request.body()).decode(errors="ignore")

    return {"status": "ok", "received": data}
