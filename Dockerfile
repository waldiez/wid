# Base images pinned by digest for supply-chain reproducibility; the tag
# comments say what the digest was resolved from (refresh deliberately).
FROM rust:slim@sha256:31ee7fc65186be7e0e0ccb3f2ca305f14e4739e7642a1ae65753aa5d7b874523 AS builder

WORKDIR /build
COPY Cargo.toml Cargo.lock* ./
COPY rust/ rust/

RUN cargo build --release

FROM debian:trixie-slim@sha256:28de0877c2189802884ccd20f15ee41c203573bd87bb6b883f5f46362d24c5c2

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/target/release/wid /usr/local/bin/wid

# An ID generator needs no root privileges. /data is writable so relative
# D= paths and E=sql state keep working (mount a volume there to persist).
RUN mkdir -p /data && chown nobody:nogroup /data
USER nobody
WORKDIR /data

ENTRYPOINT ["wid"]
CMD ["next"]
