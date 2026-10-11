# Applied only with -PruntimeCheck: instrumentation depends on classes that the
# production optimizer can otherwise inline/remove from the application's deps.
-keep class androidx.tracing.** { *; }
-keep class androidx.test.** { *; }
-keep class org.junit.** { *; }
-keep class org.hamcrest.** { *; }
-keep class app.mangalate.local.MlKitRuntimeTest { *; }
-keep class app.mangalate.local.MlKitSupport { *; }
-keep class app.mangalate.local.OnDeviceOcr { *; }
-keep class app.mangalate.local.OnDeviceTranslate { *; }
-keep class app.mangalate.translate.SourceLanguage { *; }
-keep class app.mangalate.translate.TargetLanguage { *; }
-keep class kotlinx.coroutines.BuildersKt** { *; }
-keep class kotlinx.coroutines.TimeoutKt { *; }
