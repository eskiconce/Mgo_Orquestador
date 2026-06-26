from database import SessionLocal, engine
import models
from passlib.context import CryptContext

# 1. FORZAR CREACIÓN DE TABLAS
# Esto crea la tabla 'users' si no existe
models.Base.metadata.create_all(bind=engine)

# Configuración de Hash (Seguridad)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def crear_usuario_admin():
    db = SessionLocal()
    
    print("--- CREACIÓN DE USUARIO ADMINISTRADOR ---")
    username = input("Ingrese Usuario (ej: admin): ")
    password = input("Ingrese Contraseña: ")
    email = input("Ingrese Email (opcional): ")
    
    # Verificar si ya existe
    existing_user = db.query(models.User).filter(models.User.username == username).first()
    if existing_user:
        print(f"❌ Error: El usuario '{username}' ya existe en la base de datos.")
        return

    # Crear usuario
    hashed_password = pwd_context.hash(password)
    user = models.User(
        username=username,
        email=email,
        full_name="Administrador",
        hashed_password=hashed_password,
        disabled=False
    )
    
    try:
        db.add(user)
        db.commit()
        print(f"✅ ¡ÉXITO! Usuario '{username}' creado correctamente.")
        print("Ahora reinicia el servicio del orquestador e intenta ingresar.")
    except Exception as e:
        print(f"❌ Error guardando en BD: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    crear_usuario_admin()
