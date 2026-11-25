SELECT *
FROM crossposter.items
WHERE state IN ('drafted', 'submitted')
ORDER BY id;
