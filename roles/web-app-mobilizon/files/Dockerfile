ARG MOBILIZON_IMAGE
ARG MOBILIZON_VERSION
FROM ${MOBILIZON_IMAGE}:${MOBILIZON_VERSION}

RUN set -eu; \
    cd /lib/mobilizon-*/priv/repo/migrations; \
    for migration in \
        20190806131306_add_url_to_follows_and_move_to_uuid.exs \
        20190813160207_add_url_and_uuid_to_participants.exs \
        20200218170232_move_member_id_to_uuid.exs \
        20200721131521_add_url_to_conversation.exs; \
    do \
        if ! grep -q 'add(:id, :uuid, primary_key: true)$' "${migration}"; then \
            echo "${migration} no longer contains 'add(:id, :uuid, primary_key: true)': the base image ships the PostgreSQL 18 migration fix (framagit.org/kaihuri/mobilizon merge request 1683). Drop this Dockerfile and the custom build of web-app-mobilizon." >&2; \
            exit 1; \
        fi; \
        sed -i 's/add(:id, :uuid, primary_key: true)$/add(:id, :uuid, primary_key: true, null: false)/' "${migration}"; \
    done
