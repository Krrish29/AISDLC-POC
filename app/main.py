from fastapi import FastAPI

app = FastAPI(title="AISDLC Leave Management System")


@app.get("/")
def home():
    return {
        "message": "Leave Management System is running",
        "project": "AISDLC POC",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}