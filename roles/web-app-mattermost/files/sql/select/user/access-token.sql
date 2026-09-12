SELECT count(*) FROM useraccesstokens WHERE token = %(token)s AND isactive = true;
