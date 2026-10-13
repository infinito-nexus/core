Logger.put_process_level(self(), :error)
%{"email" => email, "password" => password, "username" => username} = Jason.decode!(IO.read(:stdio, :eof))

{user, changes} =
  case Mobilizon.Users.get_user_by_email(email) do
    {:ok, user} ->
      stale_password =
        user.provider == nil and
          not (is_binary(user.password_hash) and Argon2.verify_pass(password, user.password_hash))

      attrs =
        Map.merge(
          if(user.role == :administrator, do: %{}, else: %{role: :administrator}),
          if(stale_password, do: %{password: password}, else: %{})
        )

      if attrs == %{} do
        {user, []}
      else
        {:ok, user} = Mobilizon.Users.update_user(user, attrs)
        {user, Map.keys(attrs)}
      end

    {:error, :user_not_found} ->
      {:ok, user} =
        Mobilizon.Users.register(%{
          email: email,
          password: password,
          role: :administrator,
          confirmed_at: DateTime.utc_now(),
          confirmation_sent_at: nil,
          confirmation_token: nil
        })

      {user, [:user]}
  end

changes =
  case Mobilizon.Users.get_actors_for_user(user) do
    [] ->
      Mix.Tasks.Mobilizon.Actors.Utils.create_profile(user, username, username)
      [:profile | changes]

    _ ->
      changes
  end

IO.puts("MOBILIZON_ADMINISTRATOR=" <> if(changes == [], do: "unchanged", else: "changed"))
