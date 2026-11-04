<?php
// nocheck: mirrored-unit-test - boots Snipe-IT's Laravel kernel through bootstrap/app.php and writes the branding through App\Models\Setting and the public storage disk; both only exist once the install has booted
require "vendor/autoload.php";
$app = require "bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use App\Models\Setting;
use Illuminate\Support\Facades\Storage;

const BLOCK = '#/\* infinito-design:([A-Za-z0-9+/=]*) \*/.*?/\* /infinito-design \*/\n?#s';
const ASSET = '/^design-(logo|favicon)-[0-9a-f]{12}\.png$/';
const FIELDS = ["site_name", "brand", "logo", "favicon", "header_color", "nav_link_color", "link_light_color", "link_dark_color"];
const OPEN = "/" . "*";
const CLOSE = "*" . "/";

$wanted = json_decode(base64_decode(getenv("SNIPE_IT_DESIGN")), true, 512, JSON_THROW_ON_ERROR);
$settings = Setting::getSettings();
$disk = Storage::disk("public");

$current = [];
foreach ([...FIELDS, "custom_css"] as $field) {
    $current[$field] = $settings->getRawOriginal($field);
}
$css = (string) $current["custom_css"];
$owned = preg_match(BLOCK, $css, $match) === 1;
$foreign = (string) preg_replace(BLOCK, "", $css);
$previous = $owned
    ? json_decode(base64_decode($match[1]), true, 512, JSON_THROW_ON_ERROR)
    : array_intersect_key($current, array_flip(FIELDS));

$files = [];
$block = "";
$target = $previous;
if ($wanted !== []) {
    $target = array_intersect_key($wanted, array_flip(FIELDS)) + $previous;
    foreach ($wanted["assets"] as $field) {
        $bytes = file_get_contents("/tmp/design-" . $field . ".png");
        $name = "design-" . $field . "-" . substr(sha1($bytes), 0, 12) . ".png";
        $files[$name] = $bytes;
        $target[$field] = $name;
    }
    $block = OPEN . " infinito-design:" . base64_encode(json_encode($previous)) . " " . CLOSE . "\n"
        . $wanted["custom_css"] . "\n" . OPEN . " /infinito-design " . CLOSE . "\n";
}
$target["custom_css"] = $block . $foreign === "" ? null : $block . $foreign;

$changed = false;
foreach ($files as $name => $bytes) {
    if (! $disk->exists($name)) {
        $disk->put($name, $bytes);
        $changed = true;
    }
}
foreach ($disk->files() as $name) {
    if (preg_match(ASSET, $name) === 1 && ! isset($files[$name])) {
        $disk->delete($name);
        $changed = true;
    }
}
foreach ($target as $field => $value) {
    if (($current[$field] === null) !== ($value === null) || (string) $current[$field] !== (string) $value) {
        $settings->{$field} = $value;
        $changed = true;
    }
}
if ($changed && ! $settings->save()) {
    fwrite(STDERR, "the settings row was rejected: " . json_encode($settings->getErrors()) . "\n");
    exit(1);
}
echo $changed ? "changed" : "unchanged";
