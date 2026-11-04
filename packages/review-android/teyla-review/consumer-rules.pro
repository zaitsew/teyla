# `teyla review store-check` looks for this class name in the dex files of a production artifact (and,
# on an internal build, expects to find it). R8 would rename it in a minified build; keep it.
-keep class teyla.review.ReviewOverlay { *; }
# The one activity of the overlay is started by name from the manifest.
-keep class teyla.review.ReviewActivity { *; }
