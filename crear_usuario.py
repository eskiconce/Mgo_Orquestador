from database import SessionLocal, engine
import models
from passlib.context import CryptContext

# Configuración Hash (Debe ser igual al main.py)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def crear_admin():
    db = SessionLocal()
    
    # Datos del usuario
    username = input("Usuario: ")
    password = input("Contraseña: ")
    fullname = input("Nombre Completo: ")
    email = input("Email: ")
    
    # Verificar si existe
    if db.query(models.User).filter(models.User.username == username).first():
        print("¡Error! El usuario ya existe.")
        return

    # Crear
    role = input("Rol (admin/operator/viewer) [operator]: ") or "operator"
    hashed = pwd_context.hash(password)
    user = models.User(username=username, full_name=fullname, email=email, hashed_password=hashed, role=role)
    
    db.add(user)
    db.commit()
    print(f"✅ Usuario {username} creado exitosamente.")

if __name__ == "__main__":
    # Asegura que la tabla exista
    models.Base.metadata.create_all(bind=engine)
    crear_admin()
