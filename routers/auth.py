from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

import models
from database import get_db
from core.deps import templates, verify_password, create_access_token, get_current_user
from core.config import ACCESS_TOKEN_EXPIRE_MINUTES
from core.logging_service import logger

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=templates.TemplateResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
def login_action(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        logger.warning(f"Intento de login fallido para: {username}")
        return templates.TemplateResponse("login.html", {"request": {}, "error": "Usuario o contraseña incorrectos"})
    logger.info(f"Usuario '{username}' inició sesión.")
    access_token_expires = __import__("datetime").timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("access_token")
    return response
