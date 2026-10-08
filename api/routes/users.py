"""Users management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.auth.dependencies import get_current_user, require_hod
from api.auth.security import hash_password
from api.database.models import Role, User
from api.database.session import get_db
from api.schemas.users import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("", response_model=list[UserResponse])
def list_users(
    role_id: int | None = Query(None, description="Filter by role ID"),
    search: str | None = Query(None, description="Search by username, full name, or email"),
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """List all registered users (HOD only)."""
    query = db.query(User)
    if role_id is not None:
        query = query.filter(User.role_id == role_id)
    if search:
        search_filter = f"%{search.strip()}%"
        query = query.filter(
            (User.username.ilike(search_filter))
            | (User.full_name.ilike(search_filter))
            | (User.email.ilike(search_filter))
        )
    users = query.order_by(User.id).all()
    return [UserResponse(**u.to_dict()) for u in users]


@router.post("", response_model=UserResponse)
def create_user(
    req: UserCreate,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Create a new user (HOD only)."""
    # Verify role exists
    role = db.query(Role).filter(Role.id == req.role_id, Role.is_active.is_(True)).first()
    if not role:
        raise HTTPException(status_code=400, detail="Invalid or inactive role specified.")

    # Check unique username
    if db.query(User).filter(User.username == req.username.strip()).first():
        raise HTTPException(status_code=400, detail="Username already exists.")

    # Check unique email
    if db.query(User).filter(User.email == req.email.strip().lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered.")

    # Check unique employee_id
    if req.employee_id and db.query(User).filter(User.employee_id == req.employee_id.strip()).first():
        raise HTTPException(status_code=400, detail="Employee ID already registered.")

    user = User(
        role_id=role.id,
        username=req.username.strip(),
        password_hash=hash_password(req.password),
        full_name=req.full_name.strip(),
        email=req.email.strip().lower(),
        employee_id=req.employee_id.strip() if req.employee_id else None,
        phone=req.phone.strip() if req.phone else None,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(**user.to_dict())


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user by ID (HOD or the user themselves)."""
    user_role = current_user.role.name if current_user.role else ""
    if current_user.id != user_id and user_role != "HOD":
        raise HTTPException(status_code=403, detail="Access denied.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    return UserResponse(**user.to_dict())


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    req: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update user information (HOD or self-update limited fields)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user_role = current_user.role.name if current_user.role else ""
    is_hod = user_role == "HOD"

    if not is_hod and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    if req.full_name is not None:
        user.full_name = req.full_name.strip()
    if req.email is not None:
        existing = db.query(User).filter(User.email == req.email.strip().lower(), User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email is taken by another account.")
        user.email = req.email.strip().lower()
    if req.phone is not None:
        user.phone = req.phone.strip()
    if req.password is not None and len(req.password.strip()) >= 6:
        user.password_hash = hash_password(req.password.strip())

    # Only HOD can change role, employee_id, and active status
    if is_hod:
        if req.role_id is not None:
            role = db.query(Role).filter(Role.id == req.role_id).first()
            if not role:
                raise HTTPException(status_code=400, detail="Specified role does not exist.")
            user.role_id = req.role_id
        if req.employee_id is not None:
            user.employee_id = req.employee_id.strip()
        if req.is_active is not None:
            if user.id == current_user.id and not req.is_active:
                raise HTTPException(status_code=400, detail="Cannot deactivate your own account.")
            user.is_active = req.is_active

    db.commit()
    db.refresh(user)
    return UserResponse(**user.to_dict())


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(require_hod),
    db: Session = Depends(get_db),
):
    """Deactivate or delete user account (HOD only)."""
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Soft delete / deactivate to maintain referential integrity with audits/evaluations
    user.is_active = False
    db.commit()
    return {"message": f"User '{user.username}' deactivated successfully."}
