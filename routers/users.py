from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

import models
from database import get_db
from core.deps import templates, get_current_user, pwd_context

router = APIRouter(tags=["users"])


@router.get("/ui/users", response_class=templates.TemplateResponse)
def users_list(request: Request, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Acceso denegado")
    users = db.query(models.User).order_by(models.User.username).all()
    users_json = [{"id": u.id, "username": u.username, "role": u.role, "disabled": u.disabled, "full_name": u.full_name or "", "email": u.email or ""} for u in users]
    return templates.TemplateResponse("users.html", {"request": request, "user": current_user, "users": users, "users_json": users_json})


@router.post("/ui/users/save")
def save_user(
    user_id: int = Form(0), username: str = Form(...), full_name: str = Form(...),
    email: str = Form(...), password: str = Form(""), role: str = Form("operator"),
    disabled: bool = Form(False), db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede gestionar usuarios")
    existing_email = db.query(models.User).filter(models.User.email == email, models.User.id != user_id).first()
    if existing_email:
        users = db.query(models.User).order_by(models.User.username).all()
        users_json = [{"id": u.id, "username": u.username, "role": u.role, "disabled": u.disabled, "full_name": u.full_name or "", "email": u.email or ""} for u in users]
        return templates.TemplateResponse("users.html", {"request": {}, "error": f"El email {email} ya esta en uso", "user": current_user, "users": users, "users_json": users_json})
    if user_id:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        user.username, user.full_name, user.email, user.role, user.disabled = username, full_name, email, role, disabled
        if password:
            user.hashed_password = pwd_context.hash(password)
    else:
        if db.query(models.User).filter(models.User.username == username).first():
            users = db.query(models.User).order_by(models.User.username).all()
            users_json = [{"id": u.id, "username": u.username, "role": u.role, "disabled": u.disabled, "full_name": u.full_name or "", "email": u.email or ""} for u in users]
            return templates.TemplateResponse("users.html", {"request": {}, "error": f"El usuario {username} ya existe", "user": current_user, "users": users, "users_json": users_json})
        hashed = pwd_context.hash(password) if password else pwd_context.hash("changeme123")
        user = models.User(username=username, full_name=full_name, email=email, hashed_password=hashed, role=role, disabled=disabled)
        db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        users = db.query(models.User).order_by(models.User.username).all()
        users_json = [{"id": u.id, "username": u.username, "role": u.role, "disabled": u.disabled, "full_name": u.full_name or "", "email": u.email or ""} for u in users]
        return templates.TemplateResponse("users.html", {"request": {}, "error": "Error: el email o username ya existe en el sistema", "user": current_user, "users": users, "users_json": users_json})
    return RedirectResponse("/ui/users", status_code=303)


@router.get("/ui/users/delete/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede eliminar usuarios")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return RedirectResponse("/ui/users", status_code=303)
    db.delete(user)
    db.commit()
    return RedirectResponse("/ui/users", status_code=303)
