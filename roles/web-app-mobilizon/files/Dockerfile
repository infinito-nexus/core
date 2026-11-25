ARG MOBILIZON_IMAGE
ARG MOBILIZON_VERSION
FROM ${MOBILIZON_IMAGE}:${MOBILIZON_VERSION} AS sigaltstack

RUN set -eu; \
    erts="$(ls -d /erts-*)"; \
    erts="${erts#*/erts-}"; \
    case "${erts}" in \
        "" | *[!0-9.]* | .* | *.) echo "Cannot read one erts version from the /erts-* directory of the base image, got '${erts}'." >&2; exit 1 ;; \
    esac; \
    major="${erts%%.*}"; \
    minor="${erts#*.}"; \
    minor="${minor%%.*}"; \
    if [ "${major}" -gt 17 ] || { [ "${major}" -eq 17 ] && [ "${minor}" -ge 1 ]; }; then \
        echo "erts-${erts} (OTP 29.1 or newer) sizes the alternate signal stack from sysconf(_SC_MINSIGSTKSZ) (github.com/erlang/otp pull request 11376), so the BEAM no longer trips the sigaltstack minimum of musl 1.2.6. Drop this Dockerfile and the custom build of web-app-mobilizon." >&2; \
        exit 1; \
    fi

RUN printf '%s\n' 'int sigaltstack(const stack_t *ss, stack_t *old) { return syscall(SYS_sigaltstack, ss, old); }' > /tmp/sigaltstack.c; \
    gcc -D_GNU_SOURCE -include signal.h -include sys/syscall.h -include unistd.h -O2 -shared -fPIC -o /tmp/libsigaltstack.so /tmp/sigaltstack.c

FROM ${MOBILIZON_IMAGE}:${MOBILIZON_VERSION}
ENV LD_PRELOAD=/usr/local/lib/libsigaltstack.so
COPY --from=sigaltstack /tmp/libsigaltstack.so ${LD_PRELOAD}
USER nobody
