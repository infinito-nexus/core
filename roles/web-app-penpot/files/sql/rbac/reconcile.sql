\getenv members RBAC_MEMBERS
\getenv owner_email PENPOT_RBAC_OWNER_EMAIL
\getenv team_id PENPOT_RBAC_TEAM_ID
\getenv team_name PENPOT_RBAC_TEAM_NAME
\getenv team_roles PENPOT_RBAC_TEAM_ROLES

BEGIN;

UPDATE profile
   SET fullname = accounts.name, modified_at = clock_timestamp()
  FROM (
         SELECT lower(account ->> 'email') AS email, account ->> 'name' AS name
           FROM json_array_elements(:'members'::json -> '@users') AS account
       ) AS accounts
 WHERE lower(profile.email) = accounts.email
   AND accounts.email <> ''
   AND accounts.name <> ''
   AND profile.deleted_at IS NULL
   AND profile.fullname IS DISTINCT FROM accounts.name
RETURNING 'CHANGED ' || profile.email || ' fullname';

CREATE TEMP TABLE penpot_rbac_owner ON COMMIT DROP AS
SELECT id AS profile_id
  FROM profile
 WHERE lower(email) = lower(:'owner_email')
   AND deleted_at IS NULL;

WITH created AS (
  INSERT INTO team (id, name, is_default, features)
  SELECT :'team_id'::uuid,
         :'team_name',
         false,
         (SELECT features FROM team WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 1)
    FROM penpot_rbac_owner
   WHERE NOT EXISTS (SELECT 1 FROM team WHERE id = :'team_id'::uuid)
  RETURNING id
), drafts AS (
  INSERT INTO project (id, team_id, name, is_default)
  SELECT uuid_generate_v4(), id, 'Drafts', true FROM created
  RETURNING id
), drafts_owner AS (
  INSERT INTO project_profile_rel (profile_id, project_id, is_owner, is_admin, can_edit)
  SELECT penpot_rbac_owner.profile_id, drafts.id, true, true, true
    FROM penpot_rbac_owner, drafts
  RETURNING profile_id
)
SELECT 'CHANGED team ' || :'team_name' || ' created' FROM created;

INSERT INTO team_profile_rel (team_id, profile_id, is_owner, is_admin, can_edit)
SELECT :'team_id'::uuid, profile_id, true, true, true
  FROM penpot_rbac_owner
 WHERE EXISTS (SELECT 1 FROM team WHERE id = :'team_id'::uuid)
    ON CONFLICT (team_id, profile_id) DO UPDATE
   SET is_owner = true, is_admin = true, can_edit = true, modified_at = clock_timestamp()
 WHERE (team_profile_rel.is_owner, team_profile_rel.is_admin, team_profile_rel.can_edit)
       IS DISTINCT FROM (true, true, true)
RETURNING 'CHANGED owner ' || :'owner_email';

CREATE TEMP TABLE penpot_rbac_wanted ON COMMIT DROP AS
SELECT profile.id AS profile_id,
       max(CASE :'team_roles'::json ->> grants.role
             WHEN 'admin' THEN 3 WHEN 'editor' THEN 2 WHEN 'viewer' THEN 1 END) AS rank
  FROM (
         SELECT roles.key AS role, lower(member ->> 'email') AS email
           FROM json_each(:'members'::json) AS roles(key, value),
                json_array_elements(roles.value) AS member
       ) AS grants
  JOIN profile ON lower(profile.email) = grants.email AND profile.deleted_at IS NULL
 WHERE grants.email <> ''
   AND :'team_roles'::json ->> grants.role IS NOT NULL
   AND profile.id NOT IN (SELECT profile_id FROM penpot_rbac_owner)
 GROUP BY profile.id;

INSERT INTO team_profile_rel (team_id, profile_id, is_owner, is_admin, can_edit)
SELECT :'team_id'::uuid, profile_id, false, rank = 3, rank >= 2
  FROM penpot_rbac_wanted
 WHERE EXISTS (SELECT 1 FROM team WHERE id = :'team_id'::uuid)
    ON CONFLICT (team_id, profile_id) DO UPDATE
   SET is_owner = false, is_admin = EXCLUDED.is_admin, can_edit = EXCLUDED.can_edit,
       modified_at = clock_timestamp()
 WHERE (team_profile_rel.is_owner, team_profile_rel.is_admin, team_profile_rel.can_edit)
       IS DISTINCT FROM (false, EXCLUDED.is_admin, EXCLUDED.can_edit)
RETURNING 'CHANGED ' || (SELECT email FROM profile WHERE id = team_profile_rel.profile_id)
          || CASE WHEN is_admin THEN ' admin' WHEN can_edit THEN ' editor' ELSE ' viewer' END;

CREATE TEMP TABLE penpot_rbac_gone ON COMMIT DROP AS
SELECT profile_id
  FROM team_profile_rel
 WHERE team_id = :'team_id'::uuid
   AND profile_id NOT IN (SELECT profile_id FROM penpot_rbac_owner)
   AND profile_id NOT IN (SELECT profile_id FROM penpot_rbac_wanted);

DELETE FROM file_profile_rel AS fpr
 USING file AS f
 INNER JOIN project AS p ON p.id = f.project_id
 WHERE fpr.file_id = f.id
   AND p.team_id = :'team_id'::uuid
   AND fpr.profile_id IN (SELECT profile_id FROM penpot_rbac_gone);

DELETE FROM project_profile_rel AS ppr
 USING project AS p
 WHERE ppr.project_id = p.id
   AND p.team_id = :'team_id'::uuid
   AND ppr.profile_id IN (SELECT profile_id FROM penpot_rbac_gone);

DELETE FROM team_project_profile_rel
 WHERE team_id = :'team_id'::uuid
   AND profile_id IN (SELECT profile_id FROM penpot_rbac_gone);

DELETE FROM team_profile_rel
 WHERE team_id = :'team_id'::uuid
   AND profile_id IN (SELECT profile_id FROM penpot_rbac_gone)
RETURNING 'CHANGED ' || (SELECT email FROM profile WHERE id = team_profile_rel.profile_id) || ' left';

COMMIT;
