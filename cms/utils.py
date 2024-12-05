


class RegexURLPattern:
    def __init__(self, regex, callback, default_args=None, name=None):
        from django.urls.resolvers import RegexPattern
        self.pattern = RegexPattern(regex)
        self.callback = callback
        self.default_args = default_args or {}
        self.name = name

    def resolve(self, path):
        from django.urls import ResolverMatch
        match = self.pattern.match(path)
        if match:
            # Combine matched arguments with default arguments
            kwargs = match.groupdict()
            kwargs.update(self.default_args)
            return ResolverMatch(self.callback, self.pattern.regex.pattern, kwargs, self.name)
        return None


class RegexURLResolver:
    def __init__(self, regex_pattern, urlconf_name):
        from django.urls.resolvers import RegexPattern
        self.regex_pattern = RegexPattern(regex_pattern)
        self.urlconf_name = urlconf_name

    def resolve(self, path):
        from django.urls import get_resolver
        resolver = get_resolver(self.urlconf_name)
        return resolver.resolve(path)



class LocaleRegexURLResolver(RegexURLResolver):
    def __init__(self, regex_pattern, urlconf_name):
        super().__init__(regex_pattern, urlconf_name)

    def resolve(self, path):
        # Add any custom locale-based resolving logic here if needed
        return super().resolve(path)