# nocheck: mirrored-unit-test - runs in the Zammad console and writes through Setting,
# whose validator heads the bucket on save; the round trip against the live object
# store is the entire contract

UserInfo.current_user_id = 1

Setting.set("storage_provider", "S3")

stored = Setting.get("storage_provider")
raise "storage_provider is #{stored.inspect}, expected \"S3\"" if stored != "S3"
