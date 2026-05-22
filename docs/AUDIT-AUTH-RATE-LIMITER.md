# Audit: Authentication & Rate Limiter Implementation

| Trường | Nội dung |
|---|---|
| **Branch** | `Dung` |
| **Ngày** | 20/05/2026 |
| **Tác giả** | Dung |
| **Trạng thái** | ✅ Code complete — Chờ test & review |

---

## 1. Tổng quan

Implement 2 middleware cho backend:
- **Authentication** — Đăng ký/đăng nhập bằng email + password + username, JWT token, email verification (OTP) có flag bật/tắt.
- **Rate Limiter** — Giới hạn request per IP bằng slowapi + Redis, fallback in-memory.

---

## 2. Files thay đổi

### 2.1 Files mới tạo (5 files)

| File | Dòng | Mô tả |
|---|---|---|
| `backend/app/models/user.py` | ~50 | Pydantic schemas: RegisterRequest, LoginRequest, TokenResponse, UserResponse |
| `backend/app/services/jwt_service.py` | ~45 | Tạo/decode JWT access token (HS256, configurable expire) |
| `backend/app/services/user_service.py` | ~170 | User CRUD: register, authenticate, get_by_id, get_by_email, verify_email |
| `backend/app/services/email_service.py` | ~160 | Gửi OTP 6 số qua SMTP SSL + OTPStore (in-memory, TTL 10 phút) |
| `backend/app/routers/auth.py` | ~180 | 5 endpoints: register, login, verify-email, resend-otp, me |

### 2.2 Files đã sửa (8 files)

| File | Thay đổi |
|---|---|
| `backend/requirements.txt` | +bcrypt, python-jose[cryptography], email-validator |
| `backend/app/core/config.py` | +JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS, REQUIRE_EMAIL_VERIFICATION, SMTP_*, RATE_LIMIT_* |
| `backend/app/middleware/auth.py` | Thay placeholder → JWT validation (`get_current_user`) + dev bypass (`verify_api_key`) |
| `backend/app/middleware/rate_limiter.py` | Thay placeholder → slowapi Limiter + Redis + custom 429 handler |
| `backend/app/middleware/__init__.py` | Cập nhật exports |
| `backend/app/routers/chat.py` | Gắn `@limiter.limit("20/minute")` cho POST + SSE endpoints |
| `backend/app/main.py` | Wire auth router, UserService lifecycle, rate limiter exception handler |
| `.env.example` | Thêm section Authentication, SMTP, Rate Limiting |

---

## 3. API Endpoints mới

| Method | Path | Mô tả | Auth required |
|---|---|---|---|
| POST | `/auth/register` | Đăng ký tài khoản mới | ❌ Public |
| POST | `/auth/login` | Đăng nhập → JWT token | ❌ Public |
| POST | `/auth/verify-email` | Xác thực email bằng OTP 6 số | ❌ Public |
| POST | `/auth/resend-otp` | Gửi lại mã OTP | ❌ Public |
| GET | `/auth/me` | Xem profile user hiện tại | ✅ Bearer token |

---

## 4. Cấu hình môi trường mới

```env
# Authentication
JWT_SECRET=change-me-in-production-use-a-long-random-string
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24
REQUIRE_EMAIL_VERIFICATION=false

# SMTP (Email Verification)
SMTP_HOST=mail.thanhnn.dev
SMTP_PORT=465
SMTP_USER=ctsv.test@thanhnn.dev
SMTP_PASSWORD=ctsv.testT1
SMTP_FROM_NAME=Ham Ninh AI
SMTP_USE_SSL=true

# Rate Limiting
RATE_LIMIT_DEFAULT=60/minute
RATE_LIMIT_CHAT=20/minute
```

---

## 5. Luồng hoạt động

### 5.1 Khi `REQUIRE_EMAIL_VERIFICATION=false` (mặc định)

```
POST /auth/register {username, email, password}
  → 201 Created (user record)

POST /auth/login {email, password}
  → 200 OK {access_token, token_type: "bearer"}

GET /auth/me (Header: Authorization: Bearer <token>)
  → 200 OK (user profile)
```

### 5.2 Khi `REQUIRE_EMAIL_VERIFICATION=true`

```
POST /auth/register {username, email, password}
  → 201 Created + gửi OTP 6 số qua email

POST /auth/verify-email {email, otp}
  → 200 OK {verified: true}

POST /auth/login {email, password}
  → 200 OK {access_token}
  (Nếu chưa verify → 403 Forbidden)

POST /auth/resend-otp {email}
  → 200 OK (gửi lại OTP mới)
```

### 5.3 Rate Limiting

```
Mọi endpoint: 60 requests/phút per IP (mặc định)
POST /chat + GET /chat/stream: 20 requests/phút per IP

Khi vượt giới hạn:
  → 429 Too Many Requests
  → Header: Retry-After: 60
  → Body: {"detail": "Too many requests. Please slow down.", "code": 429}
```

---

## 6. Thiết kế bảo mật

| Aspect | Implementation |
|---|---|
| Password storage | bcrypt hash (salt tự động) |
| Token | JWT HS256, expire configurable (default 24h) |
| Dev mode bypass | `APP_ENV=development` + không có Authorization header → cho qua |
| Production | Bắt buộc Bearer token cho /chat và /admin |
| OTP | 6 số ngẫu nhiên, TTL 10 phút, single-use (xóa sau khi verify) |
| SMTP | SSL (port 465), credentials từ env vars |
| Rate limit storage | Redis (distributed), fallback in-memory nếu Redis down |

---

## 7. Dependencies mới

| Package | Version | Mục đích |
|---|---|---|
| `bcrypt` | 4.3.0 | Hash password |
| `python-jose[cryptography]` | 3.4.0 | JWT encode/decode |
| `email-validator` | >=2.0 | Validate EmailStr trong Pydantic |
| `slowapi` | 0.1.9 | Rate limiting (đã có sẵn trong requirements) |

---

## 8. Database schema mới

```sql
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Bảng được tạo tự động khi `UserService` khởi tạo (auto-migration pattern giống `agent_session_messages`).

---

## 9. Tương thích ngược

- **Chat/Admin endpoints**: Vẫn hoạt động bình thường trong dev mode (không cần token).
- **Production**: Cần đăng ký → login → gửi Bearer token.
- **Health endpoint**: Không bị ảnh hưởng (public, không auth, không rate limit).
- **Existing tests**: Không bị break vì dev mode bypass vẫn hoạt động.

---

## 10. TODO / Cải thiện sau

- [ ] Chuyển OTPStore sang Redis (hiện tại in-memory, mất khi restart)
- [ ] Thêm refresh token (hiện chỉ có access token)
- [ ] Thêm endpoint đổi password
- [ ] Thêm endpoint forgot password (reset qua email)
- [ ] Rate limit per-user (authenticated) thay vì chỉ per-IP
- [ ] Viết unit tests cho auth flow
- [ ] Viết integration tests với Docker (PostgreSQL + Redis + SMTP)
