Logger.put_process_level(self(), :error)
alias Mobilizon.Admin
alias Mobilizon.Admin.SettingMedia
alias Mobilizon.Storage.Repo

%{"colors" => colors, "medias" => medias} = Jason.decode!(IO.read(:stdio, :eof))
mark_group = "infinito_design"

color_changes =
  for {name, wanted} <- colors, reduce: [] do
    acc ->
      mark = Admin.get_admin_setting_value(mark_group, name)
      current = Admin.get_admin_setting_value("instance", name)

      cond do
        wanted != nil and current == wanted and mark == wanted ->
          acc

        wanted != nil and current in [nil, mark, wanted] ->
          {:ok, _} = Admin.save_settings("instance", %{String.to_atom(name) => wanted})
          {:ok, _} = Admin.save_settings(mark_group, %{String.to_atom(name) => wanted})
          [name | acc]

        wanted == nil and mark != nil and current == mark ->
          {:ok, _} = Admin.save_settings("instance", %{String.to_atom(name) => ""})
          {:ok, _} = Admin.save_settings(mark_group, %{String.to_atom(name) => ""})
          [name | acc]

        wanted == nil and mark != nil ->
          {:ok, _} = Admin.save_settings(mark_group, %{String.to_atom(name) => ""})
          [name | acc]

        true ->
          acc
      end
  end

{:ok, owner} = Mobilizon.Actors.get_or_create_internal_actor("relay")

media_changes =
  for {name, wanted} <- medias, reduce: [] do
    acc ->
      mark_name = String.to_atom(name <> "_url")
      mark = Admin.get_admin_setting_value(mark_group, Atom.to_string(mark_name))
      current = Admin.get_admin_setting_media("instance", name)
      current_url = current && current.file.url

      cond do
        wanted != nil and current_url == wanted["url"] and mark == wanted["url"] ->
          acc

        wanted != nil and (current == nil or current_url in [mark, wanted["url"]]) ->
          {:ok, media} =
            Mobilizon.Medias.create_media(%{
              file: %{url: wanted["url"], name: wanted["name"], content_type: wanted["content_type"]},
              metadata: %{width: wanted["width"], height: wanted["height"]},
              actor_id: owner.id
            })

          Repo.insert!(%SettingMedia{group: "instance", name: name, media_id: media.id},
            on_conflict: {:replace, [:media_id, :updated_at]},
            conflict_target: [:group, :name]
          )

          if current != nil, do: Repo.delete!(current)
          {:ok, _} = Admin.save_settings(mark_group, %{mark_name => wanted["url"]})
          [name | acc]

        wanted == nil and mark != nil and current_url == mark ->
          Repo.delete!(Repo.get_by!(SettingMedia, group: "instance", name: name))
          Repo.delete!(current)
          {:ok, _} = Admin.save_settings(mark_group, %{mark_name => ""})
          [name | acc]

        wanted == nil and mark != nil ->
          {:ok, _} = Admin.save_settings(mark_group, %{mark_name => ""})
          [name | acc]

        true ->
          acc
      end
  end

changes = color_changes ++ media_changes
if changes != [], do: Mobilizon.Config.clear_config_cache()
IO.puts("MOBILIZON_DESIGN=" <> if(changes == [], do: "unchanged", else: "changed"))
