Role Integrations
=================

A role never names another role directly. It names a service key in its
``meta/services.yml``, and the key resolves to the role that provides it; an
add-on under ``meta/addons/`` reaches the same provider by naming that key in
its ``bridges:`` list. The two pages below list both sides for every
``web-app-*`` and ``web-svc-*`` role, regenerated from the roles on each build.

.. toctree::
   :maxdepth: 1

   /generated/integrations/services
   /generated/integrations/addons
