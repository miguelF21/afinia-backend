import { NgModule } from '@angular/core';
import { SharedModule } from '../shared/shared.module';
import { ShellComponent } from './shell.component';

@NgModule({
  imports: [SharedModule],
  declarations: [ShellComponent],
  exports: [ShellComponent],
})
export class LayoutModule {}
