# Session: FastAPI authentication system

**User (Turn 1):** I'm building a FastAPI authentication system for our internal
developer portal. Roughly 4,000 employees, single sign-on later, but for now
plain email plus password. Where should I start?

**Assistant (Turn 2):** Start with the token strategy, because it constrains
everything else. For an internal portal I'd use short-lived JWT access tokens
plus opaque refresh tokens stored server-side, so you can revoke a session
without rotating a signing key.

**User (Turn 3):** Okay. Access token lifetime?

**Assistant (Turn 4):** Fifteen minutes is the usual balance. Short enough that a
leaked access token expires before it is useful, long enough that clients are
not refreshing constantly.

**User (Turn 5):** Let's go with 15 minutes for access tokens and 7 days for
refresh tokens.

**Assistant (Turn 6):** Good. Record that as a decision. Refresh tokens should be
rotated on every use, and the old one revoked, so a stolen refresh token is
detectable when the legitimate client next presents it.

**User (Turn 7):** What database? We already run PostgreSQL for the main app.

**Assistant (Turn 8):** Use PostgreSQL. There is no reason to add another
datastore for session rows, and you get transactional revocation for free.

**User (Turn 9):** Decision: PostgreSQL, reusing the existing cluster. New schema
named `auth` so it does not collide with the portal tables.

**Assistant (Turn 10):** Sensible. Three tables to start: `auth.users`,
`auth.refresh_tokens`, `auth.login_attempts`.

**User (Turn 11):** Password hashing — bcrypt or argon2?

**Assistant (Turn 12):** Argon2id. It is the current OWASP recommendation and
`argon2-cffi` is a clean dependency. bcrypt is acceptable but has the 72-byte
password truncation quirk.

**User (Turn 13):** Argon2id it is. What parameters?

**Assistant (Turn 14):** Start with time_cost=3, memory_cost=65536, parallelism=4
and tune against your actual hardware until hashing takes roughly 250ms.

**User (Turn 15):** Here's my first pass at the user model.

```python
class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

**Assistant (Turn 16):** That is close. Store the email lowercased, and add a
`CITEXT` column or a functional unique index on `lower(email)` so
`Alex@corp.com` and `alex@corp.com` cannot both register.

**User (Turn 17):** Added a functional unique index on lower(email).

**Assistant (Turn 18):** Next: the refresh token table. Never store the raw
token. Store a SHA-256 hash of it, plus `issued_at`, `expires_at`,
`revoked_at`, and a `replaced_by` column so you can trace a rotation chain.

**User (Turn 19):** Why hash the refresh token if it is already random?

**Assistant (Turn 20):** Because a database dump then contains no usable
credentials. Randomness protects against guessing; hashing protects against
disclosure. They are different threats.

**User (Turn 21):** Understood. Decision: refresh tokens stored as SHA-256
hashes only, raw value returned once to the client and never persisted.

**Assistant (Turn 22):** Now the endpoints. Four to begin with:
`POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`,
`POST /auth/logout`.

**User (Turn 23):** Should registration be open?

**Assistant (Turn 24):** No, this is an internal portal. Restrict registration to
your corporate email domain and require an invite token, otherwise anyone who
reaches the endpoint can create an account.

**User (Turn 25):** Constraint: registration is restricted to @corp.com email
addresses and requires a valid invite token. No open signup, ever.

**Assistant (Turn 26):** Good. For login, always run the password hash
comparison even when the email does not exist, using a dummy hash. Otherwise
response timing leaks which emails are registered.

**User (Turn 27):** Added the dummy-hash comparison. Rate limiting?

**Assistant (Turn 28):** Five failed attempts per email per fifteen minutes, and
a separate per-IP limit. Log every attempt into `auth.login_attempts` so you
can alert on spikes.

**User (Turn 29):** Decision: 5 failures per email per 15 minutes, plus 50
attempts per IP per hour.

**Assistant (Turn 30):** For the JWT itself, sign with RS256 rather than HS256.
It lets the portal verify tokens with a public key without holding the signing
secret.

**User (Turn 31):** That means key rotation. How do I handle it?

**Assistant (Turn 32):** Publish a JWKS endpoint with a `kid` in every token
header. Keep the previous public key in the JWKS for one access-token lifetime
after rotating, so in-flight tokens still verify.

**User (Turn 33):** Decision: RS256 with a JWKS endpoint at
`/.well-known/jwks.json`, keys rotated quarterly.

**Assistant (Turn 34):** Here is the refresh endpoint skeleton.

```python
@router.post("/auth/refresh")
async def refresh(payload: RefreshIn, db: AsyncSession = Depends(get_db)):
    token_hash = sha256(payload.refresh_token.encode()).hexdigest()
    row = await repo.get_active_refresh_token(db, token_hash)
    if row is None:
        raise HTTPException(401, "invalid refresh token")
    await repo.revoke(db, row, reason="rotated")
    new_refresh = await repo.issue_refresh_token(db, row.user_id, replaces=row.id)
    return TokenPair(access=mint_access(row.user_id), refresh=new_refresh)
```

**User (Turn 35):** What happens if someone replays a revoked refresh token?

**Assistant (Turn 36):** Treat it as a breach signal. If a revoked token is
presented, revoke the entire rotation chain for that user and force a fresh
login. That is the standard reuse-detection response.

**User (Turn 37):** Decision: refresh token reuse revokes the whole chain and
forces re-authentication.

**Assistant (Turn 38):** Remaining work: wire the rate limiter into the login
route, write the Alembic migration for the `auth` schema, and add integration
tests for the rotation and reuse-detection paths.

**User (Turn 39):** Constraint I forgot to mention: we cannot add Redis. Ops has
frozen new infrastructure until the datacentre migration finishes in Q4, so the
rate limiter has to live in PostgreSQL.

**Assistant (Turn 40):** Then implement the limiter as a counter table with a
windowed unique key and an atomic upsert. It is slower than Redis but correct,
and it adds no new infrastructure.

**User (Turn 41):** Agreed. Next objective is the JWT refresh token endpoint
finished end to end, with reuse detection and the PostgreSQL rate limiter
wired into login.
