import { NgModule } from '@angular/core';

import { SharedModule } from '../../../shared/shared.module';
import { RegisterPageRoutingModule } from './register-routing.module';
import { RegisterPage } from './register.page';

@NgModule({
  imports: [SharedModule, RegisterPageRoutingModule],
  declarations: [RegisterPage]
})
export class RegisterPageModule {}
