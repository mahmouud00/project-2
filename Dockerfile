# MYTech Solutions server — for trying the system and for online deployments.

# pg_dump / pg_restore 16 (used by backups) taken from the official PostgreSQL image,
# with the few shared libraries the Python image does not have. Both images are Debian trixie.
FROM postgres:16-trixie AS pgtools
RUN mkdir -p /out/bin /out/lib \
 && cp /usr/lib/postgresql/16/bin/pg_dump /usr/lib/postgresql/16/bin/pg_restore /out/bin/ \
 && for lib in libpq.so.5 libldap.so.2 liblber.so.2 libsasl2.so.2 libgssapi_krb5.so.2 libkrb5.so.3 \
               libk5crypto.so.3 libkrb5support.so.0 libcom_err.so.2 libkeyutils.so.1; do \
      cp -L /usr/lib/x86_64-linux-gnu/$lib /out/lib/ 2>/dev/null || cp -L /lib/x86_64-linux-gnu/$lib /out/lib/; \
    done

FROM python:3.12-slim-trixie
COPY --from=pgtools /out/bin/ /usr/local/bin/
COPY --from=pgtools /out/lib/ /usr/local/lib/pgtools/
RUN echo /usr/local/lib/pgtools > /etc/ld.so.conf.d/pgtools.conf && ldconfig && pg_dump --version

WORKDIR /srv/mytech
COPY VERSION ./VERSION
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/app ./backend/app
RUN pip install --no-cache-dir ./backend
COPY backend/migrations ./backend/migrations
COPY backend/alembic.ini ./backend/alembic.ini
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /srv/mytech/backend
ENV PYTHONUNBUFFERED=1 MEDIA_DIR=/data/media BACKUP_DIR=/data/backups LICENSE_FILE=/data/license/license.json
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
